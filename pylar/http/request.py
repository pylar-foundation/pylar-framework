"""HTTP request type used throughout pylar.

For now this is a direct re-export of :class:`starlette.requests.Request`.
Pylar's typed conveniences live in adjacent layers:

* parsed and validated input bodies → :mod:`pylar.validation` (RequestDTO)
* typed path parameters             → :mod:`pylar.routing` (model binding)

Keeping ``Request`` itself thin avoids subclass-construction problems with
Starlette's internals while still giving us a single import point we can
extend later without breaking user code.
"""

from __future__ import annotations

from starlette.requests import Request

__all__ = ["Request"]
