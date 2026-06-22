"""In-memory cache with per-entry TTL and a bounded LRU eviction policy.

TTL alone never reclaims memory for keys that are written once and never read
again (e.g. a flood of unique player/item lookups), so the store is also capped
at ``_MAX_ENTRIES``: on overflow the least-recently-used entry is evicted. Reads
and writes mark an entry as most-recently-used.
"""
import logging
import time
from collections import OrderedDict

_log = logging.getLogger(__name__)
_MAX_ENTRIES = 1000
_store: "OrderedDict[str, tuple[object, float]]" = OrderedDict()


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
    _store.move_to_end(key)  # mark most-recently-used
    _log.info(f"cache_hit key={key}")
    return value


def set(key: str, value: object, ttl_seconds: int) -> None:
    _store[key] = (value, time.monotonic() + ttl_seconds)
    _store.move_to_end(key)
    while len(_store) > _MAX_ENTRIES:
        evicted, _ = _store.popitem(last=False)  # drop least-recently-used
        _log.info(f"cache_evict key={evicted}")


def invalidate(key: str) -> None:
    _store.pop(key, None)
