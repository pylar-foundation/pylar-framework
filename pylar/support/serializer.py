"""Restricted pickle serializer — blocks known RCE gadgets.

Plain ``pickle.loads()`` executes arbitrary code during
deserialization. Pylar replaces every deserialization call with
:func:`safe_loads` / :func:`safe_load`, which use a
:class:`RestrictedUnpickler` that blocks imports from modules known
to provide code-execution primitives (``os``, ``subprocess``,
``builtins``, ``sys``, etc.).

The approach is a **deny-list**: normal data types (datetime, uuid,
decimal, pydantic models, user dataclasses) pass through; only the
specific modules that attackers use to build RCE gadget chains are
blocked. This is the same strategy used by production frameworks
like Celery's ``safe`` serializer.

Serialization (``pickle.dumps``) is left unrestricted because the
application controls what it writes — the risk is only on the
*read* side where an attacker-controlled payload enters.
"""

from __future__ import annotations

import io
import pickle
from typing import Any

#: Modules whose classes are **never** allowed during deserialization.
#: These cover the standard RCE gadget chains:
#: ``os.system``, ``subprocess.Popen``, ``builtins.eval/exec``,
#: ``importlib.import_module``, ``ctypes``, ``shutil.rmtree``, etc.
_BLOCKED_MODULES = frozenset({
    "os",
    "posix",
    "nt",
    "posixpath",
    "ntpath",
    "subprocess",
    "sys",
    "builtins",
    "importlib",
    "importlib.metadata",
    "runpy",
    "code",
    "codeop",
    "compileall",
    "ctypes",
    "ctypes.util",
    "shutil",
    "signal",
    "socket",
    "multiprocessing",
    "threading",
    "webbrowser",
    "http.client",
    "http.server",
    "xmlrpc",
    "pickle",        # block recursive pickle tricks
    "_pickle",
    "shelve",
    "tempfile",
    "pathlib",       # PurePosixPath gadgets
})


class RestrictedUnpickler(pickle.Unpickler):
    """An :class:`Unpickler` that refuses to import dangerous modules.

    If a pickle stream contains a ``GLOBAL`` opcode referencing a
    blocked module, the unpickler raises :class:`pickle.UnpicklingError`
    instead of importing the class — stopping the gadget chain before
    any side effect occurs.
    """

    def find_class(self, module: str, name: str) -> type:
        top_level = module.split(".")[0]
        if module in _BLOCKED_MODULES or top_level in _BLOCKED_MODULES:
            raise pickle.UnpicklingError(
                f"Blocked deserialization of {module}.{name} — "
                f"module '{module}' is on the deny list."
            )
        result = super().find_class(module, name)
        assert isinstance(result, type)
        return result


def safe_loads(data: bytes) -> Any:
    """Deserialize *data* using the restricted unpickler.

    Drop-in replacement for ``pickle.loads()`` that blocks known RCE
    gadget chains. Use this everywhere the framework deserializes
    data that could have been tampered with (session stores, cache
    stores, queue payloads from untrusted sources).
    """
    return RestrictedUnpickler(io.BytesIO(data)).load()


def safe_load(fp: Any) -> Any:
    """Deserialize from a file object using the restricted unpickler.

    Drop-in replacement for ``pickle.load(fp)``.
    """
    return RestrictedUnpickler(fp).load()


def dumps(value: Any, *, protocol: int = 5) -> bytes:
    """Serialize *value* with pickle. Thin wrapper for symmetry."""
    return pickle.dumps(value, protocol=protocol)


def dump(value: Any, fp: Any, *, protocol: int = 5) -> None:
    """Serialize *value* to a file object. Thin wrapper for symmetry."""
    pickle.dump(value, fp, protocol=protocol)
