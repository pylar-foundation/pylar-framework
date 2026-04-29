"""Transparent encryption wrapper around any :class:`SessionStore`.

Sits between the :class:`SessionMiddleware` and the underlying store
driver. On write it pickle-serialises the session dict, encrypts the
bytes with the bound :class:`Encrypter`, and hands the ciphertext to
the inner store as a single opaque string. On read it reverses the
process. The inner store never sees the plaintext payload, so even
a compromised Redis or leaked session file reveals nothing.

Usage (in a service provider)::

    container.singleton(
        SessionStore,
        lambda: EncryptedSessionStore(
            inner=MemorySessionStore(),
            encrypter=container.make(Encrypter),
        ),
    )

When ``APP_KEY`` is set and :class:`EncryptionServiceProvider` is
registered, :class:`SessionServiceProvider` wraps the bound store
automatically — no manual wiring needed.
"""

from __future__ import annotations

import pickle
from typing import Any

from pylar.encryption.encrypter import Encrypter
from pylar.encryption.exceptions import DecryptionError
from pylar.session.store import SessionStore
from pylar.support.serializer import dumps, safe_loads


class EncryptedSessionStore:
    """Encrypt-on-write, decrypt-on-read wrapper.

    Satisfies the :class:`SessionStore` Protocol so it plugs into the
    middleware pipeline transparently.
    """

    def __init__(self, inner: SessionStore, encrypter: Encrypter) -> None:
        self._inner = inner
        self._encrypter = encrypter

    async def read(self, session_id: str) -> dict[str, Any] | None:
        raw = await self._inner.read(session_id)
        if raw is None:
            return None
        # The inner store persists the ciphertext as a single-key dict
        # ``{"_encrypted": "<token>"}`` so drivers that expect a dict
        # (like MemorySessionStore) don't break.
        token = raw.get("_encrypted") if isinstance(raw, dict) else None
        if not isinstance(token, str):
            return None
        try:
            plaintext = self._encrypter.decrypt(token)
        except DecryptionError:
            return None
        try:
            data = safe_loads(plaintext)
        except (pickle.UnpicklingError, EOFError):
            return None
        return data if isinstance(data, dict) else None

    async def write(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        plaintext = dumps(data)
        token = self._encrypter.encrypt(plaintext)
        await self._inner.write(
            session_id, {"_encrypted": token}, ttl_seconds=ttl_seconds
        )

    async def destroy(self, session_id: str) -> None:
        await self._inner.destroy(session_id)
