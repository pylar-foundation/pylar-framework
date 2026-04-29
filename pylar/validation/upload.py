"""Typed file upload support for handlers.

Pylar reuses Starlette's :class:`starlette.datastructures.UploadFile`
under the alias :class:`pylar.validation.UploadFile`. The class is
re-exported here so handler code does not have to import directly from
Starlette and so the routing layer can scan for it the same way it
scans for :class:`RequestDTO` parameters.

Usage::

    from pylar.validation import UploadFile

    async def avatar(request: Request, file: UploadFile) -> Response:
        contents = await file.read()
        ...

The router auto-resolver finds the parameter, parses
``request.form()``, and binds the file under the parameter name. If
the form does not contain a matching field a 422 ``ValidationError``
is raised — symmetric with how missing :class:`RequestDTO` fields fail.
"""

from __future__ import annotations

from starlette.datastructures import UploadFile

__all__ = ["UploadFile"]
