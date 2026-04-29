"""The Application object — owner of the container, config, and lifecycle."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pylar.foundation.container import Container
from pylar.foundation.kernel import Kernel
from pylar.foundation.provider import ServiceProvider


class AppConfig(BaseModel):
    """The minimal configuration needed to bootstrap an :class:`Application`.

    Domain-specific configs (database, mail, queue, ...) live in their own
    pydantic models under the user's ``config/`` package and are bound into the
    container by their respective service providers.

    When ``autodiscover`` is ``True`` (the default), installed packages
    that register a ``pylar.providers`` entry point are discovered
    automatically and their providers are appended after the explicit
    ``providers`` tuple.  Set ``autodiscover=False`` to opt out — all
    providers must then be listed explicitly.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str
    debug: bool = False
    providers: tuple[type[ServiceProvider], ...] = Field(default_factory=tuple)
    autodiscover: bool = True


class Application:
    """Coordinates configuration, the container, and the provider lifecycle.

    The application is constructed eagerly so that simple inspection (tests,
    CLI tooling) does not require an event loop. The asynchronous portion of
    bootstrap — and any side effects — happen inside :meth:`bootstrap`.
    """

    def __init__(
        self,
        base_path: Path,
        config: AppConfig,
        *,
        config_path: Path | None = None,
    ) -> None:
        self.base_path = base_path
        self.config = config
        self.config_path = config_path if config_path is not None else base_path / "config"
        self.container = Container()
        self._providers: list[ServiceProvider] = []
        self._booted = False
        self._register_core_bindings()

    @classmethod
    def from_config(cls) -> Application:
        """Build an :class:`Application` from the CWD's ``config/app.py``.

        Used by ``pylar dev`` (uvicorn ``--factory`` reload) and any
        environment where the application must be constructed from an
        import path rather than an already-held instance.
        """
        import importlib

        cwd = Path.cwd()
        try:
            mod = importlib.import_module("config.app")
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError(
                "Cannot import config.app — is the CWD a pylar project?"
            ) from exc
        config = getattr(mod, "config", None)
        if not isinstance(config, AppConfig):
            raise RuntimeError(
                "config/app.py must export a top-level `config: AppConfig` variable"
            )
        return cls(base_path=cwd, config=config)

    # ----------------------------------------------------------------- bootstrap

    def _register_core_bindings(self) -> None:
        self.container.instance(Application, self)
        self.container.instance(Container, self.container)
        self.container.instance(AppConfig, self.config)

    async def bootstrap(self) -> None:
        """Instantiate, register, and boot every configured service provider.

        When ``AppConfig.autodiscover`` is enabled, installed packages
        that register a ``pylar.providers`` entry point are discovered
        and appended after the explicit providers.  Duplicate classes
        (already in the explicit list) are skipped so a user who both
        lists a provider explicitly and installs it as a package does
        not get a double-registration error.

        Idempotent: subsequent calls are no-ops.
        """
        if self._booted:
            return

        # Local import: ``pylar.config`` sits *above* ``pylar.foundation`` in
        # the layering, so the dependency must not appear at module load time.
        from pylar.config.loader import ConfigLoader

        ConfigLoader(self.config_path).bind_into(self.container)

        # Merge explicit providers with auto-discovered ones.
        all_provider_classes = list(self.config.providers)
        if self.config.autodiscover:
            from pylar.foundation.plugins import discover_providers

            explicit_set = set(all_provider_classes)
            for cls in discover_providers():
                if cls not in explicit_set:
                    all_provider_classes.append(cls)

        self._providers = [provider_cls(self) for provider_cls in all_provider_classes]

        for provider in self._providers:
            provider.register(self.container)

        for provider in self._providers:
            await provider.boot(self.container)

        self._booted = True

    @property
    def is_booted(self) -> bool:
        return self._booted

    @property
    def providers(self) -> tuple[ServiceProvider, ...]:
        return tuple(self._providers)

    # ----------------------------------------------------------------------- run

    async def run(self, kernel: Kernel) -> int:
        """Bootstrap the application and hand control to *kernel*."""
        await self.bootstrap()
        try:
            return await kernel.handle()
        finally:
            await self.shutdown()

    # ------------------------------------------------------------------ teardown

    async def shutdown(self) -> None:
        """Tear providers down in reverse order.

        Errors in individual providers are caught and logged so that a
        failing provider never prevents subsequent providers from
        shutting down — partial teardown is worse than a logged error.
        """
        import logging

        if not self._booted:
            return
        logger = logging.getLogger("pylar.application")
        for provider in reversed(self._providers):
            try:
                await provider.shutdown(self.container)
            except Exception:
                logger.exception(
                    "Error shutting down %s", type(provider).__qualname__
                )
        self._booted = False
