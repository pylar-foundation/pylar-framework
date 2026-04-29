"""Tests for plugin discovery and listing."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

from pylar.foundation.commands import PackageListCommand, _PackageListInput
from pylar.foundation.plugins import (
    PluginInfo,
    discover_providers,
    list_plugins,
)
from pylar.foundation.provider import ServiceProvider


class _FakeProvider(ServiceProvider):
    """Dummy provider for testing."""


class _NotAProvider:
    """Not a ServiceProvider subclass."""


class TestDiscoverProviders:
    def test_returns_empty_when_no_plugins(self) -> None:
        with patch("pylar.foundation.plugins.importlib.metadata.entry_points", return_value=[]):
            result = discover_providers()
        assert result == []

    def test_loads_valid_provider(self) -> None:
        ep = MagicMock()
        ep.name = "fake"
        ep.value = "tests.foundation.test_plugins:_FakeProvider"
        ep.load.return_value = _FakeProvider

        with patch("pylar.foundation.plugins.importlib.metadata.entry_points", return_value=[ep]):
            result = discover_providers()

        assert len(result) == 1
        assert result[0] is _FakeProvider

    def test_skips_non_provider_class(self) -> None:
        ep = MagicMock()
        ep.name = "bad"
        ep.value = "tests.foundation.test_plugins:_NotAProvider"
        ep.load.return_value = _NotAProvider

        with patch("pylar.foundation.plugins.importlib.metadata.entry_points", return_value=[ep]):
            result = discover_providers()

        assert result == []

    def test_skips_broken_import(self) -> None:
        ep = MagicMock()
        ep.name = "broken"
        ep.value = "nonexistent.module:Cls"
        ep.load.side_effect = ImportError("no such module")

        with patch("pylar.foundation.plugins.importlib.metadata.entry_points", return_value=[ep]):
            result = discover_providers()

        assert result == []


class TestListPlugins:
    def test_returns_empty_when_no_plugins(self) -> None:
        with patch("pylar.foundation.plugins.importlib.metadata.entry_points", return_value=[]):
            result = list_plugins()
        assert result == []

    def test_reads_metadata_without_loading(self) -> None:
        ep = MagicMock()
        ep.name = "my_plugin"
        ep.value = "my_pkg.provider:MyProvider"
        ep.dist = MagicMock()
        ep.dist.name = "pylar-my-plugin"
        ep.dist.version = "1.2.3"

        with patch("pylar.foundation.plugins.importlib.metadata.entry_points", return_value=[ep]):
            result = list_plugins()

        assert len(result) == 1
        assert result[0] == PluginInfo(
            name="my_plugin",
            module="my_pkg.provider:MyProvider",
            package="pylar-my-plugin",
            version="1.2.3",
        )
        # Should NOT call load().
        ep.load.assert_not_called()


class TestPackageListCommand:
    async def test_no_plugins(self) -> None:
        from pylar.console.output import Output

        with patch("pylar.foundation.commands.list_plugins", return_value=[]):
            buf = StringIO()
            cmd = PackageListCommand(Output(buf, colour=False))
            code = await cmd.handle(_PackageListInput())
        assert code == 0
        assert "No plugin packages found" in buf.getvalue()

    async def test_with_plugins(self) -> None:
        from pylar.console.output import Output

        plugins = [
            PluginInfo(
                name="admin",
                module="pylar_admin:AdminProvider",
                package="pylar-admin",
                version="0.1.0",
            ),
            PluginInfo(
                name="sentry",
                module="pylar_sentry:SentryProvider",
                package="pylar-sentry",
                version="2.0.0",
            ),
        ]
        with patch("pylar.foundation.commands.list_plugins", return_value=plugins):
            buf = StringIO()
            cmd = PackageListCommand(Output(buf, colour=False))
            code = await cmd.handle(_PackageListInput())
        output = buf.getvalue()
        assert code == 0
        assert "pylar-admin" in output
        assert "0.1.0" in output
        assert "pylar-sentry" in output
        assert "2 plugin(s)" in output
