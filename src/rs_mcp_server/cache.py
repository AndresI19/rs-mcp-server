"""In-memory cache with per-entry TTL support."""
import logging
import time

_log = logging.getLogger(__name__)
_store: dict[str, tuple[object, float]] = {}


def get(key: str) -> object | None:
    entry = _store.get(key)
    if entry is None:
        _log.info(f"cache_miss key={key}")
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        del _store[key]
        _log.info(f"cache_miss key={key}")
        return None
    _log.info(f"cache_hit key={key}")
    return value


def set(key: str, value: object, ttl_seconds: int) -> None:
    _store[key] = (value, time.monotonic() + ttl_seconds)


def invalidate(key: str) -> None:
    _store.pop(key, None)
