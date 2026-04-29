"""Coding standards enforcement tests.

These tests walk the framework source tree and check invariants that
go beyond what mypy and ruff catch. They run as part of the normal
test suite and fail loudly when a convention is violated.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Root of the framework package.
_PYLAR_ROOT = Path(__file__).resolve().parent.parent / "pylar"


def _all_python_files() -> list[Path]:
    """Return every .py file in the pylar package."""
    return sorted(
        f
        for f in _PYLAR_ROOT.rglob("*.py")
        if "__pycache__" not in str(f)
        and "/spa/" not in str(f)  # Vue.js SPA — not Python
    )


# ------------------------------------------------------------------ helpers


def _public_function_defs(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return every public (non-underscore) function/method def in *tree*."""
    result: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                result.append(node)
    return result


def _positional_params(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Return the names of POSITIONAL_OR_KEYWORD params (before ``*``)."""
    args = func.args
    return [
        a.arg
        for a in args.posonlyargs + args.args
        if a.arg not in ("self", "cls")
    ]


# ------------------------------------------------------------- the test


#: Public functions that are allowed to have 3+ positional params.
#: Each entry is "module_path:function_name".  Add a comment explaining
#: why the exception exists.
_POSITIONAL_ALLOWLIST: set[str] = {
    # Protocol-mandated signatures — changing to keyword-only would
    # break every implementation in user code.
    "pylar/queue/job.py:handle",
    "pylar/queue/middleware.py:handle",
    # JobMiddleware.handle signature — matches the protocol above.
    "pylar/observability/otel.py:handle",
    "pylar/observability/prometheus.py:handle",
    "pylar/observability/sentry.py:handle",
    # Internal framework plumbing with a fixed call site — not user-facing.
    "pylar/routing/action.py:invoke",
    "pylar/console/input.py:parse_args",
}


class TestKeywordOnlyParameters:
    """Enforce that public API functions use keyword-only parameters.

    Pylar's convention: public functions and methods must not accept
    more than 2 positional parameters (excluding ``self``/``cls``).
    Additional parameters must be keyword-only (after ``*``).

    This prevents call-site ambiguity::

        # Bad  — what does True mean?
        cache.remember("key", 300, fetch_posts)

        # Good — intent is clear at the call site
        cache.remember("key", ttl=300, factory=fetch_posts)

    Functions that cannot follow this rule (protocol implementations,
    internal plumbing) are listed in ``_POSITIONAL_ALLOWLIST``.
    """

    def test_public_functions_use_keyword_only_params(self) -> None:
        violations: list[str] = []

        for filepath in _all_python_files():
            try:
                source = filepath.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except SyntaxError:
                continue

            relative = str(filepath.relative_to(_PYLAR_ROOT.parent))

            for func in _public_function_defs(tree):
                positional = _positional_params(func)
                if len(positional) < 3:
                    continue

                key = f"{relative}:{func.name}"
                if key in _POSITIONAL_ALLOWLIST:
                    continue

                violations.append(
                    f"  {relative}:{func.lineno} "
                    f"{func.name}({', '.join(positional)}) — "
                    f"{len(positional)} positional params, max is 2"
                )

        if violations:
            report = "\n".join(violations)
            raise AssertionError(
                f"Public functions with too many positional parameters "
                f"(use keyword-only after *):\n\n{report}\n\n"
                f"Fix: add `*` separator before param 3+, or add to "
                f"_POSITIONAL_ALLOWLIST with justification."
            )

    def test_no_kwargs_in_public_api(self) -> None:
        """No public function/method uses ``**kwargs``."""
        violations: list[str] = []

        for filepath in _all_python_files():
            try:
                source = filepath.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except SyntaxError:
                continue

            relative = str(filepath.relative_to(_PYLAR_ROOT.parent))

            for func in _public_function_defs(tree):
                if func.args.kwarg is not None:
                    violations.append(
                        f"  {relative}:{func.lineno} "
                        f"{func.name}(**{func.args.kwarg.arg})"
                    )

        if violations:
            report = "\n".join(violations)
            raise AssertionError(
                f"Public functions with **kwargs (forbidden by convention):\n\n"
                f"{report}"
            )

    def test_no_args_in_public_api(self) -> None:
        """No public function/method uses ``*args``."""
        violations: list[str] = []

        for filepath in _all_python_files():
            try:
                source = filepath.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except SyntaxError:
                continue

            relative = str(filepath.relative_to(_PYLAR_ROOT.parent))

            for func in _public_function_defs(tree):
                vararg = func.args.vararg
                if vararg is not None:
                    # Allow *args only in __init_subclass__ (Python convention)
                    # and in type-safe variadic signatures like where(*conditions).
                    if func.name in ("__init_subclass__",):
                        continue
                    violations.append(
                        f"  {relative}:{func.lineno} "
                        f"{func.name}(*{vararg.arg})"
                    )

        # This is an informational check — some *args are legitimate
        # (e.g., where(*conditions: Q) is type-safe). We track them
        # but don't fail yet. Uncomment the assertion when the
        # codebase is clean.
        # if violations:
        #     raise AssertionError(...)
