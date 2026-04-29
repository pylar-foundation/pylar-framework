"""``ApiServiceProvider`` — binds the API layer into the container.

Responsibilities:

* Register :class:`ApiErrorMiddleware` so route groups can reference it
  as a class without hand-instantiating it.
* Bind :class:`ApiDocsConfig` — lets applications turn the
  ``/openapi.json``, ``/docs`` and ``/redoc`` endpoints on/off and
  override the title/version/description shown on them.
* Mount the three OpenAPI endpoints into the application ``Router`` in
  :meth:`boot` if :attr:`ApiDocsConfig.enabled` is ``True``.
* Tag the ``api:docs`` console command.

The provider does **not** mount any user routes. Applications opt in
by attaching :class:`ApiErrorMiddleware` to whichever route group
should speak the phase-7 JSON envelope.
"""

from __future__ import annotations

from dataclasses import dataclass

from pylar.api.middleware import ApiErrorMiddleware
from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


@dataclass(frozen=True)
class ApiDocsConfig:
    """Toggle + metadata for the built-in OpenAPI viewers.

    Bound as a singleton by :class:`ApiServiceProvider`. Applications
    override via ``container.instance(ApiDocsConfig, …)`` in their own
    provider or leave the defaults and get ``/openapi.json``, ``/docs``,
    and ``/redoc`` served for free.
    """

    enabled: bool = True
    title: str = "Pylar API"
    version: str = "0.0.1"
    description: str | None = None
    servers: tuple[str, ...] = ()
    spec_path: str = "/openapi.json"
    swagger_path: str = "/docs"
    redoc_path: str = "/redoc"


class ApiServiceProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.bind(ApiErrorMiddleware, ApiErrorMiddleware)
        if not container.has(ApiDocsConfig):
            container.instance(ApiDocsConfig, ApiDocsConfig())

        # Lazy import to avoid a circular dependency between commands.py
        # (which imports pylar.console) and the provider that registers it.
        from pylar.api.commands import ApiDocsCommand

        container.tag([ApiDocsCommand], COMMANDS_TAG)

    async def boot(self, container: Container) -> None:
        cfg = container.make(ApiDocsConfig)
        if not cfg.enabled:
            return

        from pylar.api.docs_ui import redoc_html, swagger_ui_html
        from pylar.api.openapi import generate_openapi
        from pylar.http.response import HtmlResponse, JsonResponse, Response
        from pylar.routing import Router

        router = container.make(Router)

        # Cache the generated spec — the router is fixed after boot, so
        # regenerating on every request wastes CPU. A test that rebuilds
        # the router between calls is rare enough to justify the cost.
        cached_spec: dict[str, object] | None = None

        async def openapi_endpoint() -> Response:
            nonlocal cached_spec
            if cached_spec is None:
                cached_spec = generate_openapi(
                    router,
                    title=cfg.title,
                    version=cfg.version,
                    description=cfg.description,
                    servers=cfg.servers,
                )
            return JsonResponse(content=cached_spec)

        async def swagger_endpoint() -> Response:
            return HtmlResponse(
                swagger_ui_html(title=cfg.title, spec_url=cfg.spec_path)
            )

        async def redoc_endpoint() -> Response:
            return HtmlResponse(
                redoc_html(title=cfg.title, spec_url=cfg.spec_path)
            )

        router.get(cfg.spec_path, openapi_endpoint, name="openapi.spec")
        router.get(cfg.swagger_path, swagger_endpoint, name="openapi.swagger")
        router.get(cfg.redoc_path, redoc_endpoint, name="openapi.redoc")
