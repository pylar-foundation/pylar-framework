"""Backwards-compatible re-export of pylar-admin.

The admin panel has been extracted into a standalone package
``pylar-admin`` (import as ``pylar_admin``).  This shim re-exports
the public API so existing ``from pylar.admin import ...`` statements
continue to work.

Install the admin package: ``pip install pylar-admin``
"""

from pylar_admin import (  # type: ignore[import-not-found, unused-ignore]
    AdminConfig,
    AdminConfigError,
    AdminError,
    AdminRegistry,
    AdminServiceProvider,
    AdminSite,
    ModelAdmin,
    ModelNotRegisteredError,
)

__all__ = [
    "AdminConfig",
    "AdminConfigError",
    "AdminError",
    "AdminRegistry",
    "AdminServiceProvider",
    "AdminSite",
    "ModelAdmin",
    "ModelNotRegisteredError",
]
