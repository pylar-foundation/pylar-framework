"""Persist notifications into a database table for in-app feeds.

The channel stores each notification as a row in ``pylar_notifications``
with the notifiable's type + id, the notification class, a JSON
``data`` column rendered by the notification's ``to_array()`` method,
and a ``read_at`` nullable timestamp.

The table is created automatically via :meth:`DatabaseChannel.bootstrap`
(called by the provider on boot) — no separate migration needed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from pylar.notifications.contracts import Notifiable
from pylar.notifications.notification import Notification

_metadata = MetaData()

notifications_table = Table(
    "pylar_notifications",
    _metadata,
    Column("id", String(36), primary_key=True),
    Column("notifiable_type", String(255), nullable=False),
    Column("notifiable_id", String(255), nullable=False),
    Column("notification_type", String(255), nullable=False),
    Column("data", Text, nullable=False),
    Column("read_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class DatabaseChannel:
    """Persist notifications into a SQL table.

    Notifications opt in by implementing ``to_array(notifiable)``
    which returns a JSON-serialisable dict stored in the ``data``
    column.
    """

    name = "database"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def bootstrap(self) -> None:
        """Create the notifications table if it does not exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)

    async def send(
        self,
        notifiable: Notifiable,
        notification: Notification,
    ) -> None:
        to_array = getattr(notification, "to_array", None)
        if to_array is None:
            return
        data = to_array(notifiable)
        now = datetime.now(UTC)
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(notifications_table).values(
                    id=uuid4().hex,
                    notifiable_type=type(notifiable).__qualname__,
                    notifiable_id=str(
                        getattr(notifiable, "auth_identifier", "")
                        or getattr(notifiable, "id", "")
                    ),
                    notification_type=type(notification).__qualname__,
                    data=json.dumps(data),
                    read_at=None,
                    created_at=now,
                )
            )

    async def unread_for(
        self,
        notifiable_type: str,
        notifiable_id: str,
    ) -> list[dict[str, Any]]:
        """Return unread notification rows for a notifiable."""
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    select(
                        notifications_table.c.id,
                        notifications_table.c.notification_type,
                        notifications_table.c.data,
                        notifications_table.c.created_at,
                    )
                    .where(notifications_table.c.notifiable_type == notifiable_type)
                    .where(notifications_table.c.notifiable_id == notifiable_id)
                    .where(notifications_table.c.read_at.is_(None))
                    .order_by(notifications_table.c.created_at.desc())
                )
            ).all()
        return [
            {
                "id": row.id,
                "type": row.notification_type,
                "data": json.loads(row.data),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def mark_as_read(self, notification_id: str) -> None:
        """Mark a notification as read."""
        async with self._engine.begin() as conn:
            await conn.execute(
                update(notifications_table)
                .where(notifications_table.c.id == notification_id)
                .values(read_at=datetime.now(UTC))
            )
