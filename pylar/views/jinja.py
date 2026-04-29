"""Jinja2-backed implementation of :class:`ViewRenderer`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import (
    Environment,
    FileSystemBytecodeCache,
    FileSystemLoader,
    TemplateNotFound,
    select_autoescape,
)

from pylar.views.exceptions import TemplateNotFoundError


class JinjaRenderer:
    """A thin wrapper over :class:`jinja2.Environment`.

    Async rendering is enabled so handler code can ``await`` the call
    without spinning up a thread for every template. Autoescape is on
    by default for HTML, XML, JS, and ``.j2`` files; the user can opt
    out via :class:`ViewConfig`.

    When *auto_reload* is ``False`` (production) a
    :class:`FileSystemBytecodeCache` is enabled under
    ``<root>/../.jinja_cache`` so templates are compiled once per
    deploy rather than on every process start.
    """

    def __init__(
        self,
        root: Path,
        *,
        autoescape: bool = True,
        auto_reload: bool = True,
    ) -> None:
        bytecode_cache = None
        if not auto_reload:
            cache_dir = root.parent / ".jinja_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            bytecode_cache = FileSystemBytecodeCache(str(cache_dir))
        self._env = Environment(
            loader=FileSystemLoader(str(root)),
            autoescape=select_autoescape() if autoescape else False,
            enable_async=True,
            trim_blocks=True,
            lstrip_blocks=True,
            auto_reload=auto_reload,
            bytecode_cache=bytecode_cache,
        )

    async def render(self, template: str, context: dict[str, Any]) -> str:
        try:
            tmpl = self._env.get_template(template)
        except TemplateNotFound as exc:
            raise TemplateNotFoundError(template) from exc
        return await tmpl.render_async(context)

    def register_auth_helpers(self) -> None:
        """Add ``current_user``, ``is_guest``, ``can`` to every template.

        Call from a service provider's ``boot()`` after the auth layer
        is wired. Templates can then use::

            {% if not is_guest() %}
                Hello {{ current_user().name }}
            {% endif %}

            {% if can("update", post) %}
                <a href="...">Edit</a>
            {% endif %}
        """
        from pylar.auth.context import current_user_or_none

        def _is_guest() -> bool:
            return current_user_or_none() is None

        def _current_user_safe() -> Any:
            return current_user_or_none()

        self._env.globals["current_user"] = _current_user_safe
        self._env.globals["is_guest"] = _is_guest

    def register_gate_helper(self, gate: Any) -> None:
        """Add ``can(ability, subject)`` to templates.

        Requires a :class:`pylar.auth.Gate` instance::

            renderer.register_gate_helper(container.make(Gate))
        """

        async def _can(ability: str, subject: Any = None) -> bool:
            from pylar.auth.context import current_user_or_none

            user = current_user_or_none()
            if user is None:
                return False
            result: bool = await gate.allows(user, ability, subject)
            return result

        self._env.globals["can"] = _can

    def register_vite_helper(
        self,
        manifest_path: Path,
        *,
        base_url: str = "/assets/",
    ) -> None:
        """Add ``{{ asset("src/app.js") }}`` global that reads a Vite manifest.

        The Vite build produces a ``manifest.json`` mapping input paths to
        their hashed output filenames. This helper reads the manifest once
        and installs an ``asset`` global that returns the cache-busted URL::

            renderer.register_vite_helper(
                base_path / "public" / ".vite" / "manifest.json",
                base_url="/build/",
            )

        Templates then use ``{{ asset("src/app.js") }}`` to emit
        ``/build/assets/app-BkH1nm3F.js`` (or whatever hash Vite chose).
        """
        import json

        manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        def _asset(entry: str) -> str:
            info = manifest.get(entry)
            if info is None:
                return f"{base_url.rstrip('/')}/{entry}"
            filename = info.get("file", entry) if isinstance(info, dict) else entry
            return f"{base_url.rstrip('/')}/{filename}"

        self._env.globals["asset"] = _asset

    @property
    def environment(self) -> Environment:
        """Underlying Jinja2 environment, for advanced extension hooks."""
        return self._env
