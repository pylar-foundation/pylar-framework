# WebAuthn & Passkeys

Pylar ships an async WebAuthn ceremony runner as `pylar.auth.webauthn`.
The module lets apps add phishing-resistant second-factor login and
passwordless primary login without pulling a separate package. See
[ADR-0013](../architecture/adrs.md) for the design rationale.

Install the optional dependency:

```bash
pip install 'pylar[webauthn]'
```

## Configuration

`WebauthnConfig` pins the one value that is hard to change later —
the relying-party ID:

```python
from pylar.auth.webauthn import WebauthnConfig

webauthn = WebauthnConfig(
    rp_id="example.com",          # registrable domain suffix
    rp_name="Example",            # shown in the browser prompt
    user_verification="preferred",
    attestation="none",           # matches GitHub / Google / MS
    challenge_ttl_seconds=300,
    require_resident_key=False,   # True for passwordless flows
)
```

`rp_id` is a **security boundary**: every credential is bound to the
exact RP ID that registered it. Moving a deployment between domains
(`app.example.com` → `example.com` or HTTPS → HTTP) invalidates
every existing passkey. Set it once at boot, not per-request.

## Binding the server

Register the config and service in a provider:

```python
from pylar.auth.webauthn import WebauthnConfig, WebauthnServer
from pylar.foundation import Container, ServiceProvider


class AppServiceProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(
            WebauthnConfig,
            lambda: WebauthnConfig(rp_id="example.com", rp_name="Example"),
        )
        container.singleton(
            WebauthnServer,
            lambda c: WebauthnServer(c.make(WebauthnConfig)),
        )
```

## Registration ceremony

Two halves joined by the session-stored challenge:

```python
from pylar.auth.context import current_user
from pylar.auth.webauthn import WebauthnServer
from pylar.http import JsonResponse, Request, json


class PasskeyController:
    def __init__(self, webauthn: WebauthnServer) -> None:
        self.webauthn = webauthn

    async def register_begin(self, request: Request) -> JsonResponse:
        user = current_user()
        options = await self.webauthn.make_registration_options(user)
        return json(options)

    async def register_finish(self, request: Request) -> JsonResponse:
        body = await request.json()
        user = current_user()
        cred = await self.webauthn.verify_registration(
            user, body, nickname=body.get("nickname"),
        )
        return json({"id": cred.id, "nickname": cred.nickname})
```

On the browser side, feed the options to `navigator.credentials.create()`,
then POST the result back to `register_finish`. `verify_registration`
persists one `WebauthnCredential` row on success.

## Authentication ceremony

Two flavours off the same method pair:

```python
async def login_begin(self, request: Request) -> JsonResponse:
    # Discoverable-credential flow — no user hint, the browser picks.
    options = await self.webauthn.make_authentication_options()
    return json(options)

async def login_finish(
    self, request: Request, guard: Guard,
) -> JsonResponse:
    body = await request.json()
    user, _cred = await self.webauthn.verify_authentication(body)
    await guard.login(user)
    return json({"ok": True})
```

Pass a concrete user to `make_authentication_options(user)` for the
step-up / 2FA flow: the browser only offers matching credentials.
Omit it for passwordless primary login — the browser picks from
resident credentials.

`verify_authentication` automatically:

1. Looks up the credential row by the response's `id` field.
2. Resolves the `tokenable_type` / `tokenable_id` pair back to the
   owning user.
3. Calls `py_webauthn` to verify the assertion.
4. Updates `sign_count` + `last_used_at`.
5. Stamps `webauthn.assertion_at` on the ambient session so 2FA
   middleware can see the factor just passed.

## Credential management

Every registered credential is a row in `pylar_webauthn_credentials`.
Three operator surfaces cover the common tasks.

### CLI (`auth:webauthn:*`)

Ship the commands by adding `WebauthnServiceProvider` to your
`config/app.py`:

```bash
pylar auth:webauthn:list                  # every registered credential
pylar auth:webauthn:list --user-id 42     # one user's passkeys
pylar auth:webauthn:revoke 17             # drop credential #17
pylar auth:webauthn:prune --days 180      # age out unused credentials
```

`prune` is safe to run nightly from the scheduler — it only deletes
credentials whose `last_used_at` (or `created_at`, for never-used
entries) is older than the cutoff.

### Admin panel

When `pylar-admin` is installed the System menu gains a **Passkeys**
page (`/admin/system/webauthn`) showing every credential with:

- resolved user label (email / username / name, falling back to the
  raw tokenable pair on orphaned rows);
- inline rename;
- revoke button;
- transports, sign-count, registered-at, last-used-at columns.

The page surfaces `WebAuthn module is not installed` when
`pylar[webauthn]` is not present so operators see a clear signal
instead of an empty grid.

### Programmatic access

`WebauthnCredential` exposes the usual `query` surface for apps that
want their own management UI:

```python
from pylar.auth.webauthn import WebauthnCredential

# List the user's passkeys for a settings page.
creds = await WebauthnCredential.query.where(
    (WebauthnCredential.tokenable_type == f"{User.__module__}.User")
    & (WebauthnCredential.tokenable_id == str(user.id))
).all()

# Revoke one.
await WebauthnCredential.query.where(
    WebauthnCredential.id == credential_id,
).delete()
```

## Errors

Every failure path raises a subclass of `WebauthnError`:

| Exception | When |
|---|---|
| `WebauthnVerificationError` | `py_webauthn` rejects the response (bad signature, origin / RP mismatch, sign-count regression). |
| `WebauthnChallengeExpiredError` | No pending challenge, wrong ceremony label, or challenge older than `challenge_ttl_seconds`. |
| `WebauthnCredentialNotFoundError` | Assertion references a credential ID the database doesn't know. |

Catch the base class to handle any WebAuthn failure the same way:

```python
try:
    user, cred = await self.webauthn.verify_authentication(body)
except WebauthnError:
    # Treat every WebAuthn failure like a failed password attempt —
    # log, throttle, return a generic 401.
    return json({"error": "Authentication failed"}, status_code=401)
```

## Integrating with 2FA

WebAuthn and the existing TOTP primitive in `pylar.auth.totp` are
complementary. A simple policy: any enrolled factor satisfies the
step-up check. Apps read both session flags in their own
middleware:

```python
from pylar.session import current_session


def has_second_factor() -> bool:
    session = current_session()
    return (
        session.get("twofactor.totp_confirmed_at") is not None
        or session.get("webauthn.assertion_at") is not None
    )
```

This lets users keep TOTP while passkey adoption rolls out, and
removes a forced-migration moment when they re-enrol.

## Attestation policy

By default `WebauthnConfig.attestation = "none"` — the server doesn't
verify the authenticator's certificate chain. That matches GitHub /
Google / Microsoft and lets any conforming authenticator register.

When a deployment needs model-level trust decisions (regulated
industries, "only FIDO-certified keys", rejecting revoked models),
bind an :class:`AttestationVerifier` implementation and switch the
config to `"direct"`:

```python
from pathlib import Path

from pylar.auth.webauthn import (
    MetadataServiceAttestationVerifier,
    WebauthnConfig,
    WebauthnServer,
)

config = WebauthnConfig(
    rp_id="example.com",
    rp_name="Example",
    attestation="direct",
)
verifier = MetadataServiceAttestationVerifier(
    metadata_path=Path("/srv/fido-mds3.json"),
)
container.singleton(
    WebauthnServer,
    lambda: WebauthnServer(config, attestation_verifier=verifier),
)
```

The MDS JSON blob is the FIDO Alliance's authoritative manifest of
certified authenticators — operators download and verify it (JWT
signed against the FIDO root) on their own schedule, then pass the
decoded JSON to the verifier.

Two interception points:

1. **Trust roots** — the verifier returns PEM-encoded attestation
   roots per format (`packed`, `tpm`, `fido-u2f`, …). `py_webauthn`
   uses these to validate the chain.
2. **Policy check** — after the chain is accepted, the verifier is
   asked to vet the AAGUID. Rejecting returns
   `AttestationNotAllowedError` (a `WebauthnVerificationError`
   subclass) so callers catch the same exception base.

Default blocked statuses: `REVOKED`, `USER_VERIFICATION_BYPASS`,
`ATTESTATION_KEY_COMPROMISE`, `USER_KEY_REMOTE_COMPROMISE`,
`USER_KEY_PHYSICAL_COMPROMISE`. Pass `blocked_status_codes=frozenset(...)`
to override.

Apps with no MDS integration skip verification entirely by leaving
the config at `"none"` (default) — `TrustAnyAttestationVerifier`
handles that case transparently.

## Migration

The `pylar make:migration` generator ships a stub; copy it into the
project's migration directory and run `pylar migrate`:

```bash
pylar make:migration --stub webauthn_credentials
pylar migrate
```

The migration creates `pylar_webauthn_credentials` with the
appropriate indexes (unique on `credential_id`, composite on
`tokenable_type + tokenable_id`).
