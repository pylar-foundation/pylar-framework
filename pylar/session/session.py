"""The :class:`Session` handle controllers and guards interact with."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


class Session:
    """A typed wrapper around the per-request session payload.

    Instances are created by :class:`SessionMiddleware` for the
    duration of one request and exposed via :func:`current_session`.
    Reads return ``None`` for missing keys; writes mark the session
    *dirty* so the middleware knows it needs to persist the change
    before the response is sent.

    Two non-trivial methods deserve attention:

    * :meth:`flash` stores a one-shot value that will be available on
      the *next* request only and discarded after that. Pylar uses
      this for redirect-and-show-message flows that should not survive
      a page refresh.
    * :meth:`regenerate` rotates the session id while preserving the
      payload. Call this immediately after login to defeat session
      fixation attacks: the cookie before login becomes inert and the
      newly authenticated session lives under a fresh id.
    """

    def __init__(self, session_id: str, data: dict[str, Any]) -> None:
        self._id = session_id
        self._data = dict(data)
        self._dirty = False
        self._destroyed = False
        self._regenerated_from: str | None = None
        # Flash bag rotation: anything currently under "_flash:new" was
        # set during the *previous* request and should be readable
        # exactly once. We move it to "_flash:old" on construction so
        # `flash` writes during this request stay isolated and the
        # middleware can drop "_flash:old" at write-back time.
        new_flash = self._data.pop("_flash:new", None)
        if isinstance(new_flash, dict):
            self._data["_flash:old"] = new_flash
            # Mark dirty so the middleware persists the rotation —
            # otherwise a request that only *reads* flashes never
            # cleans up the prior bag and the value sticks around.
            self._dirty = True
        else:
            self._data.pop("_flash:old", None)

    # ----------------------------------------------------------- identity

    @property
    def id(self) -> str:
        return self._id

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def is_destroyed(self) -> bool:
        return self._destroyed

    @property
    def regenerated_from(self) -> str | None:
        return self._regenerated_from

    # ------------------------------------------------------------- reads

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        # Flash values from the previous request are also visible.
        old = self._data.get("_flash:old")
        if isinstance(old, dict) and key in old:
            return old[key]
        return default

    def has(self, key: str) -> bool:
        if key in self._data:
            return True
        old = self._data.get("_flash:old")
        return isinstance(old, dict) and key in old

    def all(self) -> dict[str, Any]:
        merged = {
            k: v for k, v in self._data.items() if not k.startswith("_flash:")
        }
        old = self._data.get("_flash:old")
        if isinstance(old, dict):
            merged.update(old)
        return merged

    # ------------------------------------------------------------ writes

    def put(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True

    def forget(self, key: str) -> None:
        if key in self._data:
            del self._data[key]
            self._dirty = True

    def flash(self, key: str, value: Any) -> None:
        bag = self._data.setdefault("_flash:new", {})
        if not isinstance(bag, dict):
            bag = {}
            self._data["_flash:new"] = bag
        bag[key] = value
        self._dirty = True

    def regenerate(self) -> None:
        """Rotate the id while preserving the payload (defeat fixation)."""
        self._regenerated_from = self._id
        self._id = uuid4().hex
        self._dirty = True

    def destroy(self) -> None:
        """Mark the session for deletion at write-back time."""
        self._destroyed = True
        self._dirty = True
        self._data.clear()

    # --------------------------------------------------------- middleware

    def to_payload(self) -> dict[str, Any]:
        """Return the dict the store should persist."""
        # Drop the just-read flash bag; keep newly written values.
        payload = {k: v for k, v in self._data.items() if k != "_flash:old"}
        return payload
