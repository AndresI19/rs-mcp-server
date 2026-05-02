"""In-memory cache with per-entry TTL support."""
import time

_store: dict[str, tuple[object, float]] = {}


def get(key: str) -> object | None:
    entry = _store.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        del _store[key]
        return None
    return value


def set(key: str, value: object, ttl_seconds: int) -> None:
    _store[key] = (value, time.monotonic() + ttl_seconds)


def invalidate(key: str) -> None:
    _store.pop(key, None)
