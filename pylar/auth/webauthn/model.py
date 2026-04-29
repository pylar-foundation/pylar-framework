"""SA-mapped model for a registered WebAuthn credential (ADR-0013)."""

from __future__ import annotations

import json

from pylar.database import Model, fields


class WebauthnCredential(Model):  # type: ignore[metaclass]
    """One registered credential (passkey, security key, platform auth).

    Rows are written by :meth:`WebauthnServer.verify_registration` and
    read by :meth:`WebauthnServer.verify_authentication`. The
    polymorphic ``tokenable_type`` / ``tokenable_id`` pair mirrors
    :class:`pylar.auth.ApiToken`: one table supports credentials on
    any ``Authenticatable``-satisfying model.

    Public-key bytes and the credential id are stored *raw*, not
    base64 — WebAuthn hands them to us as bytes and that's what
    ``py_webauthn`` expects back on verification. Encoding happens
    only at the HTTP/JSON boundary.
    """

    class Meta:
        db_table = "pylar_webauthn_credentials"

    tokenable_type = fields.CharField(max_length=255, index=True)
    tokenable_id = fields.CharField(max_length=64, index=True)

    credential_id = fields.BinaryField(
        unique=True, index=True, comment="Raw credential ID from the authenticator"
    )
    public_key = fields.BinaryField(comment="COSE-encoded public key")
    sign_count = fields.IntegerField(
        default=0,
        comment="Monotonic authenticator counter; regression signals cloning",
    )
    aaguid = fields.CharField(
        max_length=36, null=True, comment="Authenticator model hint, UUID format"
    )
    transports = fields.TextField(
        default="[]",
        comment="JSON array of transport hints (usb/nfc/ble/internal/hybrid)",
    )
    backup_eligible = fields.BooleanField(
        default=False, comment="BE flag — credential is syncable across devices"
    )
    backup_state = fields.BooleanField(
        default=False, comment="BS flag — credential is currently backed up / synced"
    )
    nickname = fields.CharField(
        max_length=120,
        null=True,
        comment="User-chosen label shown in credential-management UI",
    )
    last_used_at = fields.DateTimeField(null=True)
    created_at = fields.DateTimeField(auto_now_add=True)

    # ---------------------------------------------------------- helpers

    @property
    def transport_list(self) -> list[str]:
        """Parsed ``transports`` JSON as a Python list.

        WebAuthn-defined values: ``usb``, ``nfc``, ``ble``,
        ``internal``, ``hybrid``. Unknown values pass through so
        future transports don't require a model change.
        """
        raw = getattr(self, "transports", None) or "[]"
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(t) for t in parsed]

    @transport_list.setter
    def transport_list(self, values: list[str]) -> None:
        self.transports = json.dumps(list(values))  # type: ignore[assignment]
