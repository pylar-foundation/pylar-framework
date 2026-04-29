"""Service provider that wires the :class:`Encrypter`."""

from __future__ import annotations

from pylar.config import env
from pylar.console.kernel import COMMANDS_TAG
from pylar.encryption.commands import KeyGenerateCommand
from pylar.encryption.encrypter import Encrypter
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class EncryptionServiceProvider(ServiceProvider):
    """Bind a singleton :class:`Encrypter` keyed by ``APP_KEY``.

    The provider reads ``APP_KEY`` from the environment. If the key
    is missing the :class:`Encrypter` is *not* bound — features that
    depend on it (session encryption, cookie encryption) gracefully
    fall back to unencrypted operation. The ``key:generate`` command
    is always available so operators can create the key.
    """

    def register(self, container: Container) -> None:
        container.tag([KeyGenerateCommand], COMMANDS_TAG)
        app_key = env.str("APP_KEY", "")
        if app_key:
            container.singleton(Encrypter, self._make_encrypter)

    def _make_encrypter(self) -> Encrypter:
        app_key = env.str("APP_KEY", "")
        raw = Encrypter.key_from_string(app_key)
        return Encrypter(raw)
