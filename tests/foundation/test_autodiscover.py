"""Tests for Application autodiscovery integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from pylar.foundation.application import AppConfig, Application
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class _ExplicitProvider(ServiceProvider):
    registered = False

    def register(self, container: Container) -> None:
        _ExplicitProvider.registered = True


class _DiscoveredProvider(ServiceProvider):
    registered = False

    def register(self, container: Container) -> None:
        _DiscoveredProvider.registered = True


class TestAutodiscovery:
    async def test_discovered_providers_are_booted(self) -> None:
        _ExplicitProvider.registered = False
        _DiscoveredProvider.registered = False

        app = Application(
            base_path=Path("/tmp/test-autodiscover"),
            config=AppConfig(
                name="test",
                debug=True,
                providers=(_ExplicitProvider,),
                autodiscover=True,
            ),
        )

        with patch(
            "pylar.foundation.plugins.discover_providers",
            return_value=[_DiscoveredProvider],
        ):
            await app.bootstrap()

        assert _ExplicitProvider.registered
        assert _DiscoveredProvider.registered
        # Both should be in the providers list.
        provider_types = [type(p) for p in app.providers]
        assert _ExplicitProvider in provider_types
        assert _DiscoveredProvider in provider_types

    async def test_autodiscover_disabled(self) -> None:
        _DiscoveredProvider.registered = False

        app = Application(
            base_path=Path("/tmp/test-autodiscover"),
            config=AppConfig(
                name="test",
                debug=True,
                providers=(),
                autodiscover=False,
            ),
        )

        with patch(
            "pylar.foundation.plugins.discover_providers",
            return_value=[_DiscoveredProvider],
        ) as mock_discover:
            await app.bootstrap()

        # discover_providers should not be called.
        mock_discover.assert_not_called()
        assert not _DiscoveredProvider.registered

    async def test_duplicate_provider_not_registered_twice(self) -> None:
        _ExplicitProvider.registered = False

        app = Application(
            base_path=Path("/tmp/test-autodiscover"),
            config=AppConfig(
                name="test",
                debug=True,
                providers=(_ExplicitProvider,),
                autodiscover=True,
            ),
        )

        # Simulate discovery returning the same provider that's already explicit.
        with patch(
            "pylar.foundation.plugins.discover_providers",
            return_value=[_ExplicitProvider],
        ):
            await app.bootstrap()

        # Should only appear once.
        provider_types = [type(p) for p in app.providers]
        assert provider_types.count(_ExplicitProvider) == 1
