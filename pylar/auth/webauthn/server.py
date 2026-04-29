"""The ``WebauthnServer`` service — four async methods for two ceremonies.

Instantiated once per application by the container::

    from pylar.auth.webauthn import WebauthnConfig, WebauthnServer

    class AppServiceProvider(ServiceProvider):
        def register(self, container: Container) -> None:
            config = WebauthnConfig(rp_id="example.com", rp_name="Example")
            container.singleton(WebauthnConfig, lambda: config)
            container.singleton(WebauthnServer, lambda c: WebauthnServer(c.make(WebauthnConfig)))

Controllers then depend on it via normal auto-wiring and call the
four methods in pairs:

* ``make_registration_options`` / ``verify_registration``
* ``make_authentication_options`` / ``verify_authentication``

Each ceremony is split in two because WebAuthn is a challenge /
response protocol: the server generates a random challenge, the
client hands it to the authenticator, the authenticator signs it,
and the server verifies the signature. Between the two halves the
challenge lives in the user's session.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.base64url_to_bytes import base64url_to_bytes
from webauthn.helpers.bytes_to_base64url import bytes_to_base64url
from webauthn.helpers.options_to_json import options_to_json
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AttestationFormat,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from pylar.auth.contracts import Authenticatable
from pylar.auth.webauthn.attestation import (
    AttestationVerifier,
    TrustAnyAttestationVerifier,
)
from pylar.auth.webauthn.config import WebauthnConfig
from pylar.auth.webauthn.exceptions import (
    WebauthnChallengeExpiredError,
    WebauthnCredentialNotFoundError,
    WebauthnVerificationError,
)
from pylar.auth.webauthn.model import WebauthnCredential
from pylar.session.context import current_session_or_none

#: Session key that holds the pending ceremony challenge. Private
#: contract — apps should not poke at it directly.
_CHALLENGE_KEY = "_webauthn.challenge"

#: Session key stamped on successful assertion. Consumed by an
#: application's 2FA middleware (or any other step-up check) to
#: confirm the user passed a WebAuthn factor. Value is the ISO
#: timestamp of the assertion.
_ASSERTION_KEY = "webauthn.assertion_at"


class WebauthnServer:
    """High-level WebAuthn ceremony runner.

    Holds a single :class:`WebauthnConfig` and delegates the
    cryptographic heavy lifting to ``py_webauthn``. Ceremony state
    (pending challenges, origin) lives on the ambient session so
    there is no server-side state to reap if a user abandons the
    ceremony mid-flight — the challenge just ages out when the
    session cookie expires.
    """

    def __init__(
        self,
        config: WebauthnConfig,
        attestation_verifier: AttestationVerifier | None = None,
    ) -> None:
        self._config = config
        self._attestation = attestation_verifier or TrustAnyAttestationVerifier()

    @property
    def config(self) -> WebauthnConfig:
        return self._config

    # ------------------------------------------------- registration

    async def make_registration_options(
        self,
        user: Authenticatable,
        *,
        exclude_existing: bool = True,
    ) -> dict[str, Any]:
        """Generate options for ``navigator.credentials.create()``.

        The returned dict is already base64url-encoded where the
        WebAuthn spec requires and ready to JSON-serialise straight
        to the client. ``exclude_existing`` loads the user's
        already-registered credentials and includes them in
        ``excludeCredentials`` so the browser won't offer to
        re-register an authenticator the user already has on file.
        """
        exclude = (
            await self._load_exclude_credentials(user)
            if exclude_existing
            else []
        )
        options = generate_registration_options(
            rp_id=self._config.rp_id,
            rp_name=self._config.rp_name,
            user_id=_user_id_bytes(user),
            user_name=_user_label(user),
            user_display_name=_user_label(user),
            attestation=AttestationConveyancePreference(self._config.attestation),
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED
                if self._config.require_resident_key
                else ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement(
                    self._config.user_verification,
                ),
            ),
            exclude_credentials=exclude,
        )
        self._store_challenge(options.challenge, "registration")
        result: dict[str, Any] = json.loads(options_to_json(options))
        return result

    async def verify_registration(
        self,
        user: Authenticatable,
        response: dict[str, Any] | str,
        *,
        nickname: str | None = None,
        origin: str | None = None,
    ) -> WebauthnCredential:
        """Verify the browser response and persist the new credential.

        Pops the registration challenge from the session, delegates
        the cryptographic check to ``py_webauthn``, and saves one
        :class:`WebauthnCredential` row on success. Raises a
        :class:`WebauthnError` subclass on any failure — callers
        treat the whole hierarchy the same way.

        ``origin`` lets the caller pin the exact origin the browser
        should have reported (scheme + host + port). Controllers
        derive it from the incoming request so the port matches —
        the config-level default would lose the port and fail on
        any non-standard deployment (localhost:8000 in development).
        """
        challenge = self._pop_challenge("registration")
        roots = await self._collect_roots()
        try:
            verified = verify_registration_response(
                credential=response,
                expected_challenge=challenge,
                expected_rp_id=self._config.rp_id,
                expected_origin=self._expected_origin(origin),
                require_user_verification=(
                    self._config.user_verification == "required"
                ),
                pem_root_certs_bytes_by_fmt=roots,
            )
        except Exception as exc:
            raise WebauthnVerificationError(
                f"Registration verification failed: {exc}"
            ) from exc

        # Policy check happens after py_webauthn accepts the chain so
        # signatures are known valid by the time the verifier decides
        # whether the model is allowed.
        aaguid_uuid = _parse_aaguid(verified.aaguid)
        await self._attestation.check_authenticator(
            aaguid_uuid,
            attestation_format=str(getattr(verified, "fmt", "none")),
        )

        transports = _extract_transports(response)
        credential = WebauthnCredential(
            tokenable_type=_tokenable_type(user),
            tokenable_id=str(user.auth_identifier),
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            aaguid=str(verified.aaguid) if verified.aaguid else None,
            transports=json.dumps(transports),
            backup_eligible=bool(
                getattr(verified, "credential_device_type", None)
                == "multi_device"
            ),
            backup_state=bool(
                getattr(verified, "credential_backed_up", False)
            ),
            nickname=nickname,
        )
        # Persist inside an explicit transaction — DatabaseSessionMiddleware
        # deliberately does not auto-commit. Without this the credential
        # rolls back when the request scope closes and the UI shows
        # success while the row silently vanishes.
        from pylar.database import transaction

        async with transaction():
            await WebauthnCredential.query.save(credential)
        return credential

    # ----------------------------------------------- authentication

    async def make_authentication_options(
        self,
        user: Authenticatable | None = None,
    ) -> dict[str, Any]:
        """Generate options for ``navigator.credentials.get()``.

        When *user* is given (the 2FA / step-up flow), the user's
        registered credentials are passed in ``allowCredentials`` so
        the browser only considers matching authenticators. When
        *user* is ``None`` (the passwordless-primary flow) the list
        is omitted — the browser asks the platform for a
        discoverable credential and returns whichever one the user
        selects.
        """
        allow: list[PublicKeyCredentialDescriptor] | None = None
        if user is not None:
            allow = await self._load_allow_credentials(user)

        options = generate_authentication_options(
            rp_id=self._config.rp_id,
            user_verification=UserVerificationRequirement(
                self._config.user_verification,
            ),
            allow_credentials=allow,
        )
        self._store_challenge(options.challenge, "authentication")
        result: dict[str, Any] = json.loads(options_to_json(options))
        return result

    async def verify_authentication(
        self,
        response: dict[str, Any] | str,
        *,
        origin: str | None = None,
    ) -> tuple[Authenticatable, WebauthnCredential]:
        """Verify an assertion and return the owning user + credential.

        Locates the credential row by the ``id`` field of the browser
        response, reconstructs the tokenable user, delegates the
        signature check to ``py_webauthn``, and updates
        ``sign_count`` + ``last_used_at`` on success. Stamps the
        ambient session with :data:`_ASSERTION_KEY` so app-level
        middleware can see that a WebAuthn factor just passed.

        ``origin``: pass the incoming request's own origin (scheme +
        host + port) so the port survives the round-trip — matching
        :meth:`verify_registration`. The config-level fallback is
        port-stripped and only matches default-port deployments.
        """
        challenge = self._pop_challenge("authentication")
        payload = _as_dict(response)

        credential_id_b64 = payload.get("id") or payload.get("rawId")
        if not isinstance(credential_id_b64, str):
            raise WebauthnVerificationError(
                "Assertion response has no credential id"
            )
        credential_id = cast(bytes, base64url_to_bytes(credential_id_b64))

        predicate = WebauthnCredential.credential_id == credential_id  # type: ignore[comparison-overlap]
        row = await WebauthnCredential.query.where(predicate).first()  # type: ignore[arg-type]
        if row is None:
            raise WebauthnCredentialNotFoundError(
                "Unknown credential"
            )

        try:
            verified = verify_authentication_response(
                credential=payload,
                expected_challenge=challenge,
                expected_rp_id=self._config.rp_id,
                expected_origin=self._expected_origin(origin),
                credential_public_key=row.public_key,
                credential_current_sign_count=row.sign_count,
                require_user_verification=(
                    self._config.user_verification == "required"
                ),
            )
        except Exception as exc:
            raise WebauthnVerificationError(
                f"Authentication verification failed: {exc}"
            ) from exc

        user = await _resolve_tokenable(row)
        if user is None:
            raise WebauthnCredentialNotFoundError(
                "Credential tokenable could not be resolved"
            )

        row.sign_count = verified.new_sign_count
        row.last_used_at = datetime.now(UTC)
        try:
            from pylar.database import transaction

            async with transaction():
                await WebauthnCredential.query.save(row)
        except Exception:
            # Best-effort — a transient write failure shouldn't
            # reject an otherwise valid assertion.
            pass

        self._stamp_assertion()
        return user, row

    # --------------------------------------------------- internals

    async def _collect_roots(
        self,
    ) -> dict[AttestationFormat, list[bytes]] | None:
        """Pull roots from the verifier for every attestation format.

        ``py_webauthn`` accepts a mapping keyed by ``AttestationFormat``
        (so the library can pick the right roots per assertion). We
        ask the verifier for each format up-front; empty lists are
        skipped so the library falls back to skipping chain checks
        for unpopulated formats — that's the ``attestation="none"``
        default path.
        """
        if self._config.attestation == "none":
            return None
        collected: dict[AttestationFormat, list[bytes]] = {}
        for fmt in AttestationFormat:
            roots = await self._attestation.roots_for(fmt.value)
            if roots:
                collected[fmt] = list(roots)
        return collected or None

    def _expected_origin(
        self, request_origin: str | None = None,
    ) -> str | list[str]:
        """Return the origin ``py_webauthn`` should check against.

        Resolution order:

        1. A *request-supplied* origin wins — controllers pass the
           current request's scheme + host + port so the port
           survives when the app runs on anything other than the
           default 80/443 (``localhost:8000`` in development).
           We still validate the host against the configured
           ``rp_id`` so a caller can't smuggle in a foreign origin.
        2. A config-level ``origin`` — operators pin an exact value
           when running behind a rewrite that loses the request
           host (proxy fronting a different port).
        3. Derived from ``rp_id`` with the HTTPS (and HTTP for
           localhost) defaults.
        """
        if request_origin:
            if self._origin_matches_rp(request_origin):
                return request_origin
            # Fall through to the configured origin rather than trust
            # a mismatched host header. py_webauthn will reject the
            # final comparison, which is the correct outcome.
        if self._config.origin:
            return self._config.origin
        rp_id = self._config.rp_id
        if rp_id == "localhost" or rp_id.startswith("localhost:"):
            return [f"http://{rp_id}", f"https://{rp_id}"]
        return f"https://{rp_id}"

    def _origin_matches_rp(self, origin: str) -> bool:
        """Cheap host-suffix check for request-supplied origins.

        WebAuthn already enforces that ``clientData.origin``'s host
        is a registrable suffix of ``rp_id``; this guard is just so
        a forged ``Origin`` header can't steer us to trust a host
        we aren't configured for *before* py_webauthn runs its own
        check. Host comparison only — scheme and port pass through.
        """
        from urllib.parse import urlparse

        try:
            host = urlparse(origin).hostname or ""
        except ValueError:
            return False
        if not host:
            return False
        rp_id = self._config.rp_id.lower()
        return host.lower() == rp_id or host.lower().endswith("." + rp_id)

    def _store_challenge(self, challenge: bytes, ceremony: str) -> None:
        session = current_session_or_none()
        if session is None:
            raise WebauthnError(
                "WebAuthn ceremonies require an active session — "
                "mount SessionMiddleware before the ceremony route."
            )
        session.put(
            _CHALLENGE_KEY,
            {
                "challenge": bytes_to_base64url(challenge),
                "ceremony": ceremony,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def _pop_challenge(self, ceremony: str) -> bytes:
        session = current_session_or_none()
        if session is None:
            raise WebauthnChallengeExpiredError(
                "No active session carries a WebAuthn challenge"
            )
        payload = session.get(_CHALLENGE_KEY)
        # Drop the stored challenge whether we accept it or not — a
        # failed verification shouldn't leave a replayable value
        # sitting in the session.
        session.forget(_CHALLENGE_KEY)

        if not isinstance(payload, dict):
            raise WebauthnChallengeExpiredError(
                "No pending WebAuthn ceremony — call make_*_options first"
            )
        if payload.get("ceremony") != ceremony:
            raise WebauthnChallengeExpiredError(
                f"Expected {ceremony!r} ceremony, session carries "
                f"{payload.get('ceremony')!r}"
            )
        created_at_raw = payload.get("created_at")
        if isinstance(created_at_raw, str):
            try:
                created_at = datetime.fromisoformat(created_at_raw)
            except ValueError:
                raise WebauthnChallengeExpiredError(
                    "Stored challenge has a malformed timestamp"
                ) from None
            ttl = timedelta(seconds=self._config.challenge_ttl_seconds)
            if datetime.now(UTC) - created_at > ttl:
                raise WebauthnChallengeExpiredError(
                    "WebAuthn challenge expired — restart the ceremony"
                )
        challenge_b64 = payload.get("challenge")
        if not isinstance(challenge_b64, str):
            raise WebauthnChallengeExpiredError(
                "Stored challenge is malformed"
            )
        return cast(bytes, base64url_to_bytes(challenge_b64))

    def _stamp_assertion(self) -> None:
        session = current_session_or_none()
        if session is None:
            return
        session.put(_ASSERTION_KEY, datetime.now(UTC).isoformat())

    async def _load_exclude_credentials(
        self, user: Authenticatable,
    ) -> list[PublicKeyCredentialDescriptor]:
        rows = await self._user_credentials(user)
        return [_to_descriptor(row) for row in rows]

    async def _load_allow_credentials(
        self, user: Authenticatable,
    ) -> list[PublicKeyCredentialDescriptor]:
        rows = await self._user_credentials(user)
        return [_to_descriptor(row) for row in rows]

    async def _user_credentials(
        self, user: Authenticatable,
    ) -> list[WebauthnCredential]:
        predicate = (
            (WebauthnCredential.tokenable_type == _tokenable_type(user))  # type: ignore[comparison-overlap]
            & (WebauthnCredential.tokenable_id == str(user.auth_identifier))  # type: ignore[comparison-overlap]
        )
        return await WebauthnCredential.query.where(predicate).all()  # type: ignore[arg-type]


# -------------------------------------------------- module helpers


def _to_descriptor(row: WebauthnCredential) -> PublicKeyCredentialDescriptor:
    transports = _parse_transports(row.transport_list)
    raw_id: bytes = row.credential_id  # type: ignore[assignment]
    return PublicKeyCredentialDescriptor(
        id=raw_id,
        transports=transports or None,
    )


def _parse_transports(
    names: Iterable[str],
) -> list[AuthenticatorTransport]:
    out: list[AuthenticatorTransport] = []
    for name in names:
        try:
            out.append(AuthenticatorTransport(name))
        except ValueError:
            # Browsers sometimes emit transports the current library
            # doesn't know — skip rather than reject the credential.
            continue
    return out


def _extract_transports(response: dict[str, Any] | str) -> list[str]:
    """Pull the transports array out of the registration response if present."""
    payload = _as_dict(response)
    transports = (
        payload.get("response", {}).get("transports")
        if isinstance(payload.get("response"), dict)
        else None
    )
    if isinstance(transports, list):
        return [str(t) for t in transports]
    return []


def _as_dict(response: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    try:
        parsed = json.loads(response)
    except (TypeError, ValueError) as exc:
        raise WebauthnVerificationError(
            f"Browser response is not valid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise WebauthnVerificationError(
            "Browser response must be a JSON object"
        )
    return parsed


def _tokenable_type(user: Authenticatable) -> str:
    cls = type(user)
    return f"{cls.__module__}.{cls.__qualname__}"


def _user_label(user: Authenticatable) -> str:
    """Pick a human label for the authenticator UI.

    WebAuthn requires ``user.name`` and ``user.displayName`` in the
    creation options. The authenticator typically shows these back
    during selection (e.g. "Choose an account for example.com").
    """
    for attr in ("email", "username", "name"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value:
            return value
    return str(user.auth_identifier)


def _user_id_bytes(user: Authenticatable) -> bytes:
    """Stable per-user identifier passed to the authenticator.

    The WebAuthn spec recommends 64 random bytes so the identifier
    is opaque — but for the passwordless-primary flow, authenticators
    use this value to distinguish accounts on the same RP. We
    deliberately use the stringified ``auth_identifier`` so apps can
    reason about which identifier the credential is bound to.
    """
    return str(user.auth_identifier).encode("utf-8")


async def _resolve_tokenable(
    credential: WebauthnCredential,
) -> Authenticatable | None:
    qualified = str(getattr(credential, "tokenable_type", ""))
    raw_id = str(getattr(credential, "tokenable_id", ""))
    module_path, _, class_name = qualified.rpartition(".")
    if not module_path or not class_name:
        return None
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        return None
    cls = getattr(module, class_name, None)
    if cls is None:
        return None
    try:
        user = await cls.query.where(cls.id == _coerce_id(raw_id)).first()
    except Exception:
        return None
    return user  # type: ignore[no-any-return]


def _coerce_id(raw: str) -> object:
    try:
        return int(raw)
    except ValueError:
        return raw


def _parse_aaguid(raw: object) -> UUID | None:
    """Coerce py_webauthn's AAGUID field to a UUID we can look up.

    The library has historically returned either a string or a bytes
    object depending on version; accept both and return ``None`` for
    the all-zero placeholder that means "authenticator declined to
    identify itself".
    """
    if raw is None:
        return None
    try:
        if isinstance(raw, UUID):
            candidate = raw
        elif isinstance(raw, bytes):
            candidate = UUID(bytes=raw)
        else:
            candidate = UUID(str(raw))
    except (ValueError, AttributeError):
        return None
    if candidate == UUID(int=0):
        return None
    return candidate


# Re-exported at the bottom so the module-body references resolve
# even though the class is declared above — this avoids a second
# circular-import dance when app code does ``from pylar.auth.webauthn
# import WebauthnError``.
from pylar.auth.webauthn.exceptions import WebauthnError  # noqa: E402
