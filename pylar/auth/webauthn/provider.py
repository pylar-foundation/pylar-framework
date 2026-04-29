"""``WebauthnServiceProvider`` — opt-in wiring for WebAuthn.

Apps that install ``pylar[webauthn]`` and want to expose the server
and CLI commands add this provider to their ``config/app.py``
alongside the existing auth provider. Nothing from this module is
loaded unless the provider is registered, so apps that skip the
extras pay no import cost.

Typical wiring::

    # config/app.py
    from pylar.auth import AuthServiceProvider
    from pylar.auth.webauthn import WebauthnConfig, WebauthnServiceProvider

    providers = (
        AuthServiceProvider,
        WebauthnServiceProvider,
        # ...
    )

    # config/auth.py (or anywhere before the container boots)
    webauthn_config = WebauthnConfig(rp_id="example.com", rp_name="Example")

Apps that prefer to bind ``WebauthnConfig`` themselves can skip the
provider's config-loader by binding a :class:`WebauthnConfig`
singleton before the provider's ``register`` runs.
"""

from __future__ import annotations

import importlib
import logging

from pylar.auth.webauthn.commands import (
    WebauthnListCommand,
    WebauthnPruneCommand,
    WebauthnRevokeCommand,
)
from pylar.auth.webauthn.config import WebauthnConfig
from pylar.auth.webauthn.server import WebauthnServer
from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider

_logger = logging.getLogger("pylar.auth.webauthn")


class WebauthnServiceProvider(ServiceProvider):
    """Register the WebAuthn server and management commands.

    * Binds :class:`WebauthnConfig` from ``config/webauthn.py`` (if
      present). Apps that bind their own config earlier skip the
      loader — the provider respects a pre-existing binding.
    * Binds :class:`WebauthnServer` as a singleton. The server is
      the entry point controllers inject.
    * Tags the three ``auth:webauthn:*`` commands into the console
      kernel so ``pylar`` discovers them.
    """

    def register(self, container: Container) -> None:
        container.tag(
            [
                WebauthnListCommand,
                WebauthnRevokeCommand,
                WebauthnPruneCommand,
            ],
            COMMANDS_TAG,
        )

        if not container.has(WebauthnConfig):
            config = self._load_config()
            if config is not None:
                container.instance(WebauthnConfig, config)

        # The container's auto-wiring resolves WebauthnServer's single
        # constructor dependency (WebauthnConfig) at first make() — no
        # explicit factory needed.
        if container.has(WebauthnConfig) and not container.has(WebauthnServer):
            container.singleton(WebauthnServer, WebauthnServer)

    def _load_config(self) -> WebauthnConfig | None:
        """Best-effort load of ``config/webauthn.py`` at register time.

        The file is expected to export a module-level ``config`` that
        is a :class:`WebauthnConfig`. Missing file is fine — apps
        often bind the config directly in their service provider.
        """
        try:
            module = importlib.import_module("config.webauthn")
        except (ImportError, ModuleNotFoundError):
            return None
        candidate = getattr(module, "config", None)
        if isinstance(candidate, WebauthnConfig):
            return candidate
        _logger.warning(
            "config/webauthn.py does not export a WebauthnConfig; "
            "WebauthnServer will not be bound automatically."
        )
        return None
