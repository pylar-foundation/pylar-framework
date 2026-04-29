"""Password hashing primitives.

Pylar ships with two built-in hashers, both exposed through the
:class:`PasswordHasher` Protocol so installations can swap them at the
container level:

* :class:`Pbkdf2PasswordHasher` — the default. PBKDF2-HMAC-SHA256 with
  OWASP's 2023 iteration count (600,000 rounds). No native dependencies,
  works on every Python install.
* :class:`Argon2PasswordHasher` — opt-in via the ``pylar[auth]`` extra.
  Argon2id (winner of the password-hashing competition), the modern
  recommendation when you can take an additional native dependency.
  Backed by ``argon2-cffi``.

Both encode their parameters into the hash string so verification works
without out-of-band metadata, and both use constant-time comparisons.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from argon2 import PasswordHasher as _Argon2Hasher


@runtime_checkable
class PasswordHasher(Protocol):
    """The contract every password hasher must satisfy."""

    def hash(self, password: str) -> str: ...

    def verify(self, password: str, hashed: str) -> bool: ...


class Pbkdf2PasswordHasher:
    """PBKDF2-HMAC-SHA256, OWASP-recommended iteration count, no extra deps.

    Hashes are encoded as ``pbkdf2_sha256$iterations$salt$hash``. Verification
    uses :func:`hmac.compare_digest` to defeat timing oracles.
    """

    ALGORITHM = "pbkdf2_sha256"
    DEFAULT_ITERATIONS = 600_000
    SALT_LENGTH_BYTES = 16

    def __init__(self, iterations: int = DEFAULT_ITERATIONS) -> None:
        if iterations < 100_000:
            raise ValueError(
                "Pbkdf2PasswordHasher refuses to use fewer than 100,000 iterations"
            )
        self._iterations = iterations

    def hash(self, password: str) -> str:
        salt = secrets.token_hex(self.SALT_LENGTH_BYTES)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            self._iterations,
        )
        return f"{self.ALGORITHM}${self._iterations}${salt}${digest.hex()}"

    def verify(self, password: str, hashed: str) -> bool:
        try:
            algorithm, iterations_str, salt, expected = hashed.split("$")
        except ValueError:
            return False
        if algorithm != self.ALGORITHM:
            return False
        try:
            iterations = int(iterations_str)
        except ValueError:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            iterations,
        )
        return hmac.compare_digest(actual.hex(), expected)


class Argon2PasswordHasher:
    """Argon2id hasher, opt-in via the ``pylar[auth]`` extra.

    Wraps ``argon2.PasswordHasher`` from ``argon2-cffi``. The defaults
    track the library's recommendations (which themselves track OWASP):
    ``time_cost=2``, ``memory_cost=19_456`` KiB, ``parallelism=1``.
    Subclass or pass tuned values to the constructor for higher-load
    deployments.

    Hashes are encoded in the standard PHC string format
    (``$argon2id$v=19$m=...,t=...,p=...$salt$hash``), so they are
    self-describing — verification needs only the stored string.

    The ``argon2-cffi`` package is imported lazily so that pylar's
    core install (which does not depend on it) keeps working. Trying
    to instantiate this class without the extra installed raises
    :class:`ImportError` with an actionable message.
    """

    DEFAULT_TIME_COST = 2
    DEFAULT_MEMORY_COST = 19_456  # KiB — OWASP 2023 recommendation
    DEFAULT_PARALLELISM = 1

    def __init__(
        self,
        *,
        time_cost: int = DEFAULT_TIME_COST,
        memory_cost: int = DEFAULT_MEMORY_COST,
        parallelism: int = DEFAULT_PARALLELISM,
    ) -> None:
        try:
            from argon2 import PasswordHasher as _Hasher
        except ImportError as exc:  # pragma: no cover - exercised via the auth extra
            raise ImportError(
                "Argon2PasswordHasher requires argon2-cffi. "
                "Install pylar with the auth extra: pip install 'pylar[auth]'."
            ) from exc

        self._hasher: _Argon2Hasher = _Hasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
        )

    def hash(self, password: str) -> str:
        result: str = self._hasher.hash(password)
        return result

    def verify(self, password: str, hashed: str) -> bool:
        # argon2-cffi raises specific exceptions for mismatch / invalid
        # inputs; pylar normalises both to ``False`` so the public API
        # of every PasswordHasher matches.
        try:
            from argon2.exceptions import (
                InvalidHashError,
                VerificationError,
                VerifyMismatchError,
            )
        except ImportError:  # pragma: no cover
            return False

        try:
            return bool(self._hasher.verify(hashed, password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        except Exception:
            return False

    def needs_rehash(self, hashed: str) -> bool:
        """Return ``True`` when the stored hash uses outdated parameters."""
        result: bool = self._hasher.check_needs_rehash(hashed)
        return result


# Silence the unused-import warning when TYPE_CHECKING is False.
_ = Any
