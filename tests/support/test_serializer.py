"""Tests for the restricted pickle serializer."""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from pylar.support.serializer import dumps, safe_loads

# --------------------------------------------------- safe types pass through


def test_primitives() -> None:
    for value in [42, 3.14, True, None, "hello", b"bytes"]:
        assert safe_loads(dumps(value)) == value


def test_collections() -> None:
    data = {
        "list": [1, 2, 3],
        "tuple": (1, 2),
        "set": {1, 2, 3},
        "frozenset": frozenset({"a", "b"}),
        "nested": {"a": [{"b": 1}]},
    }
    result = safe_loads(dumps(data))
    assert result["list"] == [1, 2, 3]
    assert result["frozenset"] == frozenset({"a", "b"})


def test_datetime_types() -> None:
    now = datetime.now(UTC)
    delta = timedelta(hours=1)
    result = safe_loads(dumps({"dt": now, "delta": delta}))
    assert result["dt"] == now
    assert result["delta"] == delta


def test_decimal() -> None:
    val = Decimal("3.14159")
    assert safe_loads(dumps(val)) == val


def test_uuid() -> None:
    val = uuid4()
    assert safe_loads(dumps(val)) == val


@dataclass(frozen=True)
class _UserSnapshot:
    id: int
    name: str


def test_user_dataclass() -> None:
    snap = _UserSnapshot(id=1, name="Alice")
    assert safe_loads(dumps(snap)) == snap


# -------------------------------------------------- dangerous types blocked


def _make_rce_payload() -> bytes:
    """Build a pickle payload that would call os.system('echo pwned')."""
    # This is the classic RCE gadget: pickle GLOBAL opcode loads
    # os.system, then REDUCE calls it with the argument.

    class _Evil:
        def __reduce__(self) -> tuple[object, tuple[str]]:  # type: ignore[override]
            return (os.system, ("echo pwned",))

    return pickle.dumps(_Evil())


def test_os_system_blocked() -> None:
    payload = _make_rce_payload()
    with pytest.raises(pickle.UnpicklingError, match="os"):
        safe_loads(payload)


def test_subprocess_blocked() -> None:
    import subprocess

    class _Sub:
        def __reduce__(self) -> tuple[object, tuple[list[str]]]:  # type: ignore[override]
            return (subprocess.call, (["echo", "pwned"],))

    with pytest.raises(pickle.UnpicklingError, match="subprocess"):
        safe_loads(pickle.dumps(_Sub()))


def test_builtins_eval_blocked() -> None:
    class _Eval:
        def __reduce__(self) -> tuple[object, tuple[str]]:  # type: ignore[override]
            return (eval, ("1+1",))

    with pytest.raises(pickle.UnpicklingError, match="builtins"):
        safe_loads(pickle.dumps(_Eval()))


def test_importlib_blocked() -> None:
    import importlib

    class _Import:
        def __reduce__(self) -> tuple[object, tuple[str]]:  # type: ignore[override]
            return (importlib.import_module, ("os",))

    with pytest.raises(pickle.UnpicklingError, match="importlib"):
        safe_loads(pickle.dumps(_Import()))


def test_shutil_blocked() -> None:
    import shutil

    class _Rm:
        def __reduce__(self) -> tuple[object, tuple[str]]:  # type: ignore[override]
            return (shutil.rmtree, ("/tmp/nonexistent",))

    with pytest.raises(pickle.UnpicklingError, match="shutil"):
        safe_loads(pickle.dumps(_Rm()))


# ----------------------------------------- verify existing stores still work


async def test_file_session_store_uses_restricted(tmp_path: object) -> None:
    """Smoke test: FileSessionStore round-trips through safe_load."""
    from pathlib import Path

    from pylar.session.stores.file import FileSessionStore

    store = FileSessionStore(Path(str(tmp_path)) / "sessions")
    now = datetime.now(UTC)
    await store.write("sid", {"ts": now, "n": 42}, ttl_seconds=60)
    data = await store.read("sid")
    assert data is not None
    assert data["ts"] == now
    assert data["n"] == 42


async def test_redis_cache_store_uses_restricted() -> None:
    """Smoke test: RedisCacheStore round-trips through safe_loads."""
    pytest.importorskip("fakeredis")
    from fakeredis.aioredis import FakeRedis

    from pylar.cache.drivers.redis import RedisCacheStore

    store = RedisCacheStore(FakeRedis(), prefix="test:")
    await store.put("k", {"dt": datetime.now(UTC)})
    result = await store.get("k")
    assert result is not None
    assert isinstance(result["dt"], datetime)
