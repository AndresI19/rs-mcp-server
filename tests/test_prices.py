"""End-to-end tests for the get_item_price MCP tool (issue #28)."""
import pytest

from rs_mcp_server.tools.prices import get_item_price


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
