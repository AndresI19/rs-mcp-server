"""End-to-end tests for the search_wiki MCP tool (issue #28)."""
import pytest

from rs_mcp_server.tools.wiki import search_wiki


class TestSearchWiki:
    @pytest.mark.anyio
    async def test_happy_path_rs3(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return {
                "query": {
                    "pages": [
                        {"title": "Zulrah", "extract": "A serpent boss."},
                    ]
                }
            }

        monkeypatch.setattr("rs_mcp_server.tools.wiki.http_get", fake_http_get)
        result = await search_wiki("zulrah", "rs3")
        assert "**Zulrah**" in result
        assert "RS3 Wiki" in result
        assert "A serpent boss." in result

    @pytest.mark.anyio
    async def test_no_results_returns_friendly_message(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return {"query": {"pages": []}}

        monkeypatch.setattr("rs_mcp_server.tools.wiki.http_get", fake_http_get)
        result = await search_wiki("zzznotathing", "osrs")
        assert result.startswith("No results found")
        assert "OSRS" in result
