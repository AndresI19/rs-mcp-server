"""End-to-end tests for the get_item_price MCP tool (issue #28, #41)."""
import pytest

from rs_mcp_server import cache as _cache_mod
from rs_mcp_server.tools.prices import get_item_price


@pytest.fixture(autouse=True)
def _reset_cache():
    _cache_mod._store.clear()
    yield


class TestGetItemPriceRs3:
    @pytest.mark.anyio
    async def test_happy_path(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "runescape.wiki" in url:
                return {
                    "query": {
                        "pages": [
                            {
                                "revisions": [
                                    {"content": "itemId = 4151\nitem = 'Abyssal whip'"}
                                ]
                            }
                        ]
                    }
                }
            if "itemdb_rs" in url:
                return {
                    "item": {
                        "current": {"price": "1m", "trend": "neutral"},
                        "today": {"price": "+5"},
                        "day30": {"change": "+2.0%"},
                        "day90": {"change": "+5.0%"},
                    }
                }
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Abyssal whip", "rs3")
        assert "**Abyssal whip**" in result
        assert "RS3 Grand Exchange" in result
        assert "Price:" in result

    @pytest.mark.anyio
    async def test_item_not_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return {"query": {"pages": [{"missing": True}]}}

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("nosuchitem", "rs3")
        assert result.startswith("Item 'nosuchitem' not found")
        assert "RS3" in result


class TestGetItemPriceOsrs:
    @pytest.mark.anyio
    async def test_happy_path(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "mapping" in url:
                return [{"id": 385, "name": "Shark"}]
            if "latest" in url:
                return {"data": {"385": {"high": 1000, "low": 900}}}
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Shark", "osrs")
        assert "**Shark**" in result
        assert "OSRS Grand Exchange" in result
        assert "Instant buy:" in result

    @pytest.mark.anyio
    async def test_item_not_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "mapping" in url:
                return []
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("nosuchitem", "osrs")
        assert result.startswith("Item 'nosuchitem' not found")
        assert "OSRS" in result

    @pytest.mark.anyio
    async def test_5m_aggregates_appended(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "mapping" in url:
                return [{"id": 4151, "name": "Abyssal whip"}]
            if url.endswith("/latest"):
                return {"data": {"4151": {"high": 1217964, "low": 1205009}}}
            if url.endswith("/5m"):
                return {"data": {"4151": {
                    "avgHighPrice": 1218000, "highPriceVolume": 715,
                    "avgLowPrice": 1204500, "lowPriceVolume": 708,
                }}}
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Abyssal whip", "osrs")
        assert "Instant buy:  1,217,964 gp" in result
        assert "5-min avg buy:  1,218,000 gp  (volume: 715)" in result
        assert "5-min avg sell: 1,204,500 gp  (volume: 708)" in result

    @pytest.mark.anyio
    async def test_no_5m_data_omitted(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "mapping" in url:
                return [{"id": 1965, "name": "Cabbage"}]
            if url.endswith("/latest"):
                return {"data": {"1965": {"high": 50, "low": 40}}}
            if url.endswith("/5m"):
                return {"data": {}}  # untraded in the last bucket
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Cabbage", "osrs")
        assert "Instant buy:" in result
        assert "5-min avg" not in result

    @pytest.mark.anyio
    async def test_5m_endpoint_failure_swallowed(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "mapping" in url:
                return [{"id": 1965, "name": "Cabbage"}]
            if url.endswith("/latest"):
                return {"data": {"1965": {"high": 50, "low": 40}}}
            if url.endswith("/5m"):
                raise RuntimeError("transient outage")
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Cabbage", "osrs")
        assert "Instant buy:" in result
        assert "5-min avg" not in result


class TestGetItemPriceRs3StreetPrices:
    """Issue #41 — geprice.com integration on top of the existing RS3 GE flow."""

    @pytest.mark.anyio
    async def test_street_price_appended_when_geprice_has_item(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "runescape.wiki" in url:
                return {"query": {"pages": [{"revisions": [{"content": "itemId = 4151\nitem = 'Abyssal whip'"}]}]}}
            if "itemdb_rs" in url:
                return {"item": {"current": {"price": "1m", "trend": "neutral"}}}
            if "geprice.com" in url:
                return [{"id": 4151, "name": "Abyssal whip", "currentWeekAverage": 950000, "weeklyChangePercent": "-3.20%"}]
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Abyssal whip", "rs3")
        assert "**Abyssal whip** (RS3 Grand Exchange)" in result
        assert "Price:   1m gp" in result
        assert "Street avg (this week): 950,000 gp  (-3.20%)" in result

    @pytest.mark.anyio
    async def test_no_street_price_when_geprice_zero(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "runescape.wiki" in url:
                return {"query": {"pages": [{"revisions": [{"content": "itemId = 59350\nitem = \"Tumeken's Light\""}]}]}}
            if "itemdb_rs" in url:
                return {"item": {"current": {"price": "2.2b", "trend": "neutral"}}}
            if "geprice.com" in url:
                return [{"id": 59350, "name": "Tumeken's Light", "currentWeekAverage": 0, "weeklyChangePercent": "-"}]
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Tumeken's Light", "rs3")
        assert "RS3 Grand Exchange" in result
        assert "Street avg" not in result

    @pytest.mark.anyio
    async def test_off_ge_only_falls_back_to_geprice(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "runescape.wiki" in url:
                return {"query": {"pages": [{"missing": True}]}}
            if "geprice.com" in url:
                return [{"id": 59344, "name": "Mask of Tumeken's Resplendence",
                         "currentWeekAverage": 349000000, "weeklyChangePercent": "-5.48%"}]
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Mask of Tumeken's Resplendence", "rs3")
        assert "**Mask of Tumeken's Resplendence** (RS3 community trades)" in result
        assert "Street avg (this week): 349,000,000 gp  (-5.48%)" in result

    @pytest.mark.anyio
    async def test_neither_ge_nor_geprice_returns_not_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "runescape.wiki" in url:
                return {"query": {"pages": [{"missing": True}]}}
            if "geprice.com" in url:
                return []
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("zzznotanitemzzz", "rs3")
        assert result.startswith("Item 'zzznotanitemzzz' not found")

    @pytest.mark.anyio
    async def test_geprice_failure_doesnt_break_ge_response(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "runescape.wiki" in url:
                return {"query": {"pages": [{"revisions": [{"content": "itemId = 4151\nitem = 'Abyssal whip'"}]}]}}
            if "itemdb_rs" in url:
                return {"item": {"current": {"price": "1m", "trend": "neutral"}}}
            if "geprice.com" in url:
                raise RuntimeError("transient outage")
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake_http_get)
        result = await get_item_price("Abyssal whip", "rs3")
        assert "**Abyssal whip** (RS3 Grand Exchange)" in result
        assert "Price:   1m gp" in result
        assert "Street avg" not in result
