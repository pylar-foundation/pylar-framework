"""Console commands for managing registered WebAuthn credentials.

Three operator-facing commands, all opt-in via
:class:`WebauthnServiceProvider`:

* ``auth:webauthn:list`` — enumerate registered credentials, optionally
  scoped to one tokenable (user).
* ``auth:webauthn:revoke <id>`` — drop a single credential by its
  primary key. Irreversible; the user has to re-enrol.
* ``auth:webauthn:prune --days N`` — drop credentials the user hasn't
  touched in *N* days. Intended to run on a cron; default 180 days.

No ``create`` command ships — credential enrolment requires a real
browser ceremony and cannot be performed from the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pylar.auth.webauthn.model import WebauthnCredential
from pylar.console.command import Command
from pylar.console.output import Output
from pylar.database.exceptions import RecordNotFoundError


def _as_aware(value: datetime) -> datetime:
    """Coerce a DB-returned naive UTC timestamp into an aware one.

    SQLite returns naive datetimes through asyncio, while PostgreSQL
    returns timezone-aware values. Normalising here keeps the prune
    comparison portable without adding a DB-specific cast.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _format_ts(value: datetime | None) -> str:
    if value is None:
        return "—"
    return _as_aware(value).strftime("%Y-%m-%d %H:%M UTC")


def _format_label(credential: WebauthnCredential) -> str:
    """Compact credential label — nickname if present, otherwise AAGUID tail."""
    nickname = getattr(credential, "nickname", None)
    if isinstance(nickname, str) and nickname:
        return nickname
    aaguid = str(getattr(credential, "aaguid", "") or "")
    return aaguid[-8:] if aaguid else "—"


# ---------------------------------------------------- auth:webauthn:list


@dataclass(frozen=True)
class _WebauthnListInput:
    user_id: str = field(
        default="",
        metadata={"help": "Restrict to credentials owned by this tokenable id"},
    )


class WebauthnListCommand(Command[_WebauthnListInput]):
    """``pylar auth:webauthn:list`` — table of registered credentials."""

    name = "auth:webauthn:list"
    description = "List registered WebAuthn credentials"
    input_type = _WebauthnListInput

    def __init__(self, output: Output) -> None:
        self.out = output

    async def handle(self, input: _WebauthnListInput) -> int:
        if input.user_id:
            rows_data = await WebauthnCredential.query.where(
                WebauthnCredential.tokenable_id == input.user_id,  # type: ignore[arg-type,comparison-overlap]
            ).all()
        else:
            rows_data = await WebauthnCredential.query.all()
        # Newest first for the CLI table. SA string ordering would be
        # typed-stricter but the table is small and in-Python sort
        # keeps the call chain simple.
        rows_data.sort(
            key=lambda c: c.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

        if not rows_data:
            self.out.info("No WebAuthn credentials registered.")
            return 0

        rows: list[tuple[str, ...]] = [
            (
                str(c.id),
                f"{c.tokenable_type}:{c.tokenable_id}",
                _format_label(c),
                _format_ts(c.created_at),
                _format_ts(c.last_used_at),
            )
            for c in rows_data
        ]
        self.out.table(
            headers=("ID", "User", "Label", "Registered", "Last used"),
            rows=rows,
            title="WebAuthn Credentials",
        )
        self.out.newline()
        self.out.info(f"{len(rows_data)} credential(s).")
        return 0


# --------------------------------------------------- auth:webauthn:revoke


@dataclass(frozen=True)
class _WebauthnRevokeInput:
    credential_id: str = field(
        metadata={"help": "Primary key of the credential to revoke"},
    )


class WebauthnRevokeCommand(Command[_WebauthnRevokeInput]):
    """``pylar auth:webauthn:revoke <id>`` — delete one credential.

    The user affected must re-enrol. Use this when a passkey is lost
    or compromised; the list command shows the integer id.
    """

    name = "auth:webauthn:revoke"
    description = "Delete a single WebAuthn credential by id"
    input_type = _WebauthnRevokeInput

    def __init__(self, output: Output) -> None:
        self.out = output

    async def handle(self, input: _WebauthnRevokeInput) -> int:
        try:
            pk = int(input.credential_id)
        except ValueError:
            self.out.error(
                f"Credential id must be an integer, got {input.credential_id!r}."
            )
            return 1

        try:
            credential = await WebauthnCredential.query.get(pk)
        except RecordNotFoundError:
            self.out.error(f"No credential with id {pk}.")
            return 1

        label = _format_label(credential)
        await WebauthnCredential.query.where(
            WebauthnCredential.id == pk,  # type: ignore[attr-defined]
        ).delete()
        self.out.success(
            f"Revoked credential {pk} ({label}) for "
            f"{credential.tokenable_type}:{credential.tokenable_id}."
        )
        return 0


# ---------------------------------------------------- auth:webauthn:prune


@dataclass(frozen=True)
class _WebauthnPruneInput:
    days: int = field(
        default=180,
        metadata={"help": "Drop credentials unused for this many days (default: 180)"},
    )


class WebauthnPruneCommand(Command[_WebauthnPruneInput]):
    """``pylar auth:webauthn:prune`` — drop stale credentials.

    "Stale" means ``last_used_at`` (or ``created_at`` for never-used
    credentials) is older than ``--days``. Designed to run on a
    nightly cron so abandoned passkeys from deleted accounts or
    one-off enrolments don't accumulate in the table forever.
    """

    name = "auth:webauthn:prune"
    description = "Drop WebAuthn credentials unused for the given number of days"
    input_type = _WebauthnPruneInput

    def __init__(self, output: Output) -> None:
        self.out = output

    async def handle(self, input: _WebauthnPruneInput) -> int:
        if input.days <= 0:
            self.out.error("--days must be a positive integer.")
            return 1

        cutoff = datetime.now(UTC) - timedelta(days=input.days)
        # Walk every credential and decide per-row — simpler than
        # expressing "COALESCE(last_used_at, created_at) < cutoff" in
        # the driver-agnostic query layer, and the credential table is
        # expected to stay small (O(users * factors)).
        all_credentials = await WebauthnCredential.query.all()
        to_remove = [
            c for c in all_credentials
            if _as_aware(c.last_used_at or c.created_at) < cutoff
        ]
        for credential in to_remove:
            await WebauthnCredential.query.where(
                WebauthnCredential.id == credential.id,  # type: ignore[attr-defined]
            ).delete()

        if not to_remove:
            self.out.info(f"No credentials older than {input.days} days.")
        else:
            self.out.success(
                f"Pruned {len(to_remove)} credential(s) older than {input.days} days."
            )
        return 0
