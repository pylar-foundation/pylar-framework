"""Tests for the tinker command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pylar.console.tinker import TinkerCommand, TinkerInput, _discover_models
from pylar.database.model import Model
from pylar.foundation.application import AppConfig, Application
from pylar.foundation.container import Container


class TestDiscoverModels:
    def test_finds_model_subclasses(self) -> None:
        """Model subclasses imported at module scope are discovered."""
        models = _discover_models()
        # At minimum, test models from conftest files will be present.
        names = {m.__name__ for m in models}
        # The exact set depends on what's imported, but Model itself
        # should never be in the result.
        assert "Model" not in names
        # All results should be actual Model subclasses.
        for cls in models:
            assert issubclass(cls, Model)
            assert hasattr(cls, "__tablename__")


class TestTinkerCommand:
    def test_build_namespace_contains_app(self) -> None:
        container = Container()
        app = MagicMock(spec=Application)
        app.config = AppConfig(name="test", debug=True, providers=())

        cmd = TinkerCommand(app=app, container=container)
        ns = cmd._build_namespace()

        assert ns["app"] is app
        assert ns["container"] is container

    def test_build_namespace_contains_framework_helpers(self) -> None:
        container = Container()
        app = MagicMock(spec=Application)
        app.config = AppConfig(name="test", debug=True, providers=())

        cmd = TinkerCommand(app=app, container=container)
        ns = cmd._build_namespace()

        # Framework helpers should be pre-imported.
        assert "transaction" in ns
        assert "Q" in ns
        assert "F" in ns

    def test_build_banner(self) -> None:
        container = Container()
        app = MagicMock(spec=Application)
        app.config = AppConfig(name="test-app", debug=True, providers=())

        cmd = TinkerCommand(app=app, container=container)
        ns = cmd._build_namespace()
        banner = cmd._build_banner(ns)

        assert "Pylar Tinker" in banner
        assert "app, container" in banner

    async def test_falls_back_to_stdlib(self) -> None:
        container = Container()
        app = MagicMock(spec=Application)
        app.config = AppConfig(name="test", debug=True, providers=())

        cmd = TinkerCommand(app=app, container=container)

        # Mock both IPython (to raise ImportError) and code.interact.
        with patch.object(cmd, "_start_ipython", side_effect=ImportError):
            with patch.object(cmd, "_start_stdlib", return_value=0) as mock_stdlib:
                code = await cmd.handle(TinkerInput())

        assert code == 0
        mock_stdlib.assert_called_once()
