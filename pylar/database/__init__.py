"""Async typed database layer for pylar — SQLAlchemy 2.0 underneath."""

from pylar.database import fields
from pylar.database.config import DatabaseConfig
from pylar.database.connection import ConnectionManager
from pylar.database.exceptions import (
    DatabaseError,
    NoActiveSessionError,
    RecordNotFoundError,
)
from pylar.database.expressions import F, Q
from pylar.database.fields import Field
from pylar.database.manager import Manager
from pylar.database.middleware import DatabaseSessionMiddleware
from pylar.database.model import Model
from pylar.database.observer import Observer
from pylar.database.paginator import Paginator, SimplePaginator
from pylar.database.provider import DatabaseServiceProvider
from pylar.database.queryset import QuerySet
from pylar.database.seeding import SEEDERS_TAG, Seeder
from pylar.database.session import (
    ambient_session,
    current_session,
    current_session_or_none,
    override_session,
    use_session,
)
from pylar.database.soft_deletes import SoftDeletes
from pylar.database.sync_manager import SyncManager, SyncQuerySet, run_sync
from pylar.database.timestamps import TimestampsMixin
from pylar.database.transaction import transaction

__all__ = [
    "SEEDERS_TAG",
    "ConnectionManager",
    "DatabaseConfig",
    "DatabaseError",
    "DatabaseServiceProvider",
    "DatabaseSessionMiddleware",
    "F",
    "Field",
    "Manager",
    "Model",
    "NoActiveSessionError",
    "Observer",
    "Paginator",
    "Q",
    "QuerySet",
    "RecordNotFoundError",
    "Seeder",
    "SimplePaginator",
    "SoftDeletes",
    "SyncManager",
    "SyncQuerySet",
    "TimestampsMixin",
    "ambient_session",
    "current_session",
    "current_session_or_none",
    "fields",
    "override_session",
    "run_sync",
    "transaction",
    "use_session",
]
