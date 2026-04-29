"""Plugin/package discovery via Python entry points.

Third-party pylar packages register their service providers under the
``pylar.providers`` entry-point group in their ``pyproject.toml``::

    [project.entry-points."pylar.providers"]
    my_package = "my_package.provider:MyServiceProvider"

Multiple providers can be registered from a single package::

    [project.entry-points."pylar.providers"]
    admin = "pylar_admin.provider:AdminServiceProvider"
    admin_api = "pylar_admin.api:ApiServiceProvider"

The application discovers and loads them automatically during
bootstrap when ``AppConfig.autodiscover`` is ``True`` (the default).
This is the equivalent of Laravel's package auto-discovery via
``composer.json`` extras.

Set ``autodiscover=False`` in your ``AppConfig`` to disable and list
all providers explicitly — useful for production deployments where
you want full control over the provider order.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass

from pylar.foundation.provider import ServiceProvider

_logger = logging.getLogger("pylar.plugins")

#: Entry-point group under which third-party packages register their
#: service providers.
ENTRY_POINT_GROUP = "pylar.providers"


@dataclass(frozen=True)
class PluginInfo:
    """Metadata about a discovered plugin entry point.

    Used by the ``package:list`` command to display installed plugins
    without needing to load them.
    """

    name: str
    module: str
    package: str
    version: str


def discover_providers() -> list[type[ServiceProvider]]:
    """Scan installed packages for pylar service providers.

    Returns a list of provider classes found under the
    ``pylar.providers`` entry-point group.  Each loaded class is
    validated as a :class:`ServiceProvider` subclass — entries that
    fail to load or point to a non-provider class are logged and
    skipped.  A broken plugin should not prevent the application
    from starting.
    """
    providers: list[type[ServiceProvider]] = []
    group = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)

    for ep in group:
        try:
            cls = ep.load()
        except Exception:
            _logger.exception(
                "Failed to load plugin provider %s (%s)",
                ep.name,
                ep.value,
            )
            continue

        if not isinstance(cls, type) or not issubclass(cls, ServiceProvider):
            _logger.warning(
                "Plugin entry point %s (%s) does not point to a "
                "ServiceProvider subclass — skipping",
                ep.name,
                ep.value,
            )
            continue

        providers.append(cls)
        _logger.debug("Discovered plugin provider: %s → %s", ep.name, cls.__qualname__)

    return providers


def list_plugins() -> list[PluginInfo]:
    """Return metadata for every installed ``pylar.providers`` entry point.

    Unlike :func:`discover_providers` this does NOT load the entry
    points — it only reads metadata so it is safe to call even when
    some plugins have broken imports.
    """
    plugins: list[PluginInfo] = []
    group = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)

    for ep in group:
        # Resolve the distribution (package) that owns this entry point.
        dist_name = ""
        dist_version = ""
        try:
            # ep.dist is available in Python 3.12+.
            dist = ep.dist
            if dist is not None:
                dist_name = dist.name
                dist_version = dist.version
        except Exception:
            pass

        plugins.append(PluginInfo(
            name=ep.name,
            module=ep.value,
            package=dist_name,
            version=dist_version,
        ))

    return plugins
