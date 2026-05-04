"""End-to-end cache validation through a tool (issue #19).

The unit tests in test_cache.py cover the cache primitive in isolation
(get/set/TTL boundaries). These tests exercise the cache through a real
tool — get_item_price — to validate that a second identical call within
the TTL window short-circuits the network entirely, and that a call
issued after the entry's TTL expires re-fetches.

If a future tool author wires the cache incorrectly (sets but never
gets, or never sets), these tests are the safety net.
"""
import pytest

from rs_mcp_server import cache
from rs_mcp_server.tools.prices import _TTL_PRICE, get_item_price


def _spy_http_get():
    """Return (fake_http_get, calls list) — the fake serves canned OSRS
    mapping + latest + 5m payloads and records every URL it was asked for."""
    calls: list[str] = []

    async def fake_http_get(url, params=None, timeout=10.0):
        calls.append(url)
        if url.endswith("/mapping"):
            return [{"id": 385, "name": "Shark"}]
        if url.endswith("/latest"):
            return {"data": {"385": {"high": 1000, "low": 900}}}
        if url.endswith("/5m"):
            return {"data": {"385": {"avgHighPrice": 980, "highPriceVolume": 50}}}
        raise AssertionError(f"unexpected URL: {url}")

    return fake_http_get, calls


# ── Sequential warm-hit ────────────────────────────────────────────────────────

class TestCacheHitWithinTtl:
    @pytest.mark.anyio
    async def test_second_identical_call_skips_network(self, monkeypatch):
        fake, calls = _spy_http_get()
        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake)

        first = await get_item_price("Shark", "osrs")
        cold_call_count = len(calls)
        second = await get_item_price("Shark", "osrs")

        # Same input must produce the same rendered output…
        assert first == second
        # …and the warm call must not have hit the network at all,
        # regardless of how many endpoints the cold path fanned out to.
        assert len(calls) == cold_call_count
        # Sanity: the cold call did fire something (caught misconfigured fake).
        assert cold_call_count > 0

    @pytest.mark.anyio
    async def test_warm_hit_logs_cache_hit(self, monkeypatch, caplog):
        fake, _calls = _spy_http_get()
        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake)

        await get_item_price("Shark", "osrs")
        caplog.clear()
        with caplog.at_level("INFO", logger="rs_mcp_server.cache"):
            await get_item_price("Shark", "osrs")

        # The cache module logs cache_hit / cache_miss at INFO; warm path is hit.
        assert any("cache_hit" in r.getMessage() for r in caplog.records)


# ── Sequential cold-after-expiry ───────────────────────────────────────────────

class TestCacheMissAfterTtl:
    @pytest.mark.anyio
    async def test_call_after_ttl_expiry_refetches(self, monkeypatch):
        # Drive cache.time.monotonic via a list cell so the test can advance
        # the clock between the two calls.
        clock = [1000.0]
        monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])

        fake, calls = _spy_http_get()
        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake)

        # Cold call at t=1000 — primes the price + mapping + 5m caches.
        await get_item_price("Shark", "osrs")
        cold_calls = list(calls)

        # Advance past the price TTL (300s) but not past the mapping TTL (86400s).
        # The 5m cache happens to share the 300s TTL too, so it also expires here.
        clock[0] = 1000.0 + _TTL_PRICE + 1

        # Second call: price + 5m caches expired → re-fire /latest and /5m.
        # Mapping cache still hot (24h TTL) → no second /mapping fetch.
        await get_item_price("Shark", "osrs")

        latest_calls = [c for c in calls if c.endswith("/latest")]
        mapping_calls = [c for c in calls if c.endswith("/mapping")]
        assert len(latest_calls) == 2, "/latest must be re-fetched after price TTL expiry"
        assert len(mapping_calls) == 1, "/mapping is cached for 24h; should not re-fire"
        # And the cold-call set is intact (we didn't lose it).
        assert all(c in calls for c in cold_calls)
