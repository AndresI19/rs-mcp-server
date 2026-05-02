"""Unit tests for cache.py (issue #18)."""
import pytest

import cache


@pytest.fixture(autouse=True)
def reset_cache():
    """Each test gets a fresh in-memory store."""
    cache._store.clear()
    yield
    cache._store.clear()


# ── get / set round-trips ─────────────────────────────────────────────────────

class TestGet:
    def test_missing_key_returns_none(self):
        assert cache.get("nope") is None

    def test_fresh_value_returned(self):
        cache.set("k", "v", ttl_seconds=60)
        assert cache.get("k") == "v"


class TestSet:
    def test_round_trip(self):
        cache.set("k", {"complex": "value"}, ttl_seconds=10)
        assert cache.get("k") == {"complex": "value"}

    def test_overwrite_existing_key(self):
        cache.set("k", "first", ttl_seconds=10)
        cache.set("k", "second", ttl_seconds=10)
        assert cache.get("k") == "second"

    def test_none_as_value_is_indistinguishable_from_missing(self):
        # Documented quirk: storing None looks like a cache miss on get()
        cache.set("k", None, ttl_seconds=10)
        assert cache.get("k") is None


# ── invalidate ────────────────────────────────────────────────────────────────

class TestInvalidate:
    def test_removes_existing_key(self):
        cache.set("k", "v", ttl_seconds=60)
        cache.invalidate("k")
        assert cache.get("k") is None

    def test_safe_noop_for_missing_key(self):
        # Should not raise
        cache.invalidate("never-existed")


# ── TTL semantics with monkeypatched time.monotonic ───────────────────────────

class TestTtl:
    def test_within_ttl_returns_value(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
        cache.set("k", "v", ttl_seconds=10)
        clock[0] = 1005.0
        assert cache.get("k") == "v"

    def test_past_ttl_returns_none(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
        cache.set("k", "v", ttl_seconds=10)
        clock[0] = 1011.0
        assert cache.get("k") is None

    def test_boundary_at_exactly_ttl_returns_value(self, monkeypatch):
        # Implementation uses strict `>`, so equal times still hit.
        clock = [1000.0]
        monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
        cache.set("k", "v", ttl_seconds=10)
        clock[0] = 1010.0
        assert cache.get("k") == "v"

    def test_expired_entry_removed_from_store(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
        cache.set("k", "v", ttl_seconds=10)
        clock[0] = 1020.0
        cache.get("k")
        assert "k" not in cache._store
