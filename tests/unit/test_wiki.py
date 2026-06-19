"""End-to-end tests for the search_wiki MCP tool (issues #28, #79)."""
import pytest

from rs_mcp_server import cache as _cache_mod
from rs_mcp_server.tools._aliases import expand_aliases
from rs_mcp_server.tools.wiki import search_wiki


@pytest.fixture(autouse=True)
def _reset_cache():
    _cache_mod._store.clear()
    yield


def _search_pages(*titles: str) -> dict:
    return {"query": {"pages": [{"title": t} for t in titles]}}


def _parse_html(html_body: str) -> dict:
    return {"parse": {"text": html_body}}


class TestSearchWiki:
    @pytest.mark.anyio
    async def test_happy_path_rs3(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if params.get("action") == "query":
                return _search_pages("Zulrah")
            if params.get("action") == "parse":
                return _parse_html("<p>A serpent boss.</p>")
            raise AssertionError(f"unexpected params: {params}")

        monkeypatch.setattr("rs_mcp_server.tools.wiki.http_get", fake_http_get)
        result = await search_wiki("zulrah", "rs3")
        assert "**Zulrah**" in result
        assert "RS3 Wiki" in result
        assert "A serpent boss." in result

    @pytest.mark.anyio
    async def test_no_results_returns_friendly_message(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _search_pages()  # empty for any search

        monkeypatch.setattr("rs_mcp_server.tools.wiki.http_get", fake_http_get)
        result = await search_wiki("zzznotathing", "osrs")
        assert result.startswith("No results found")
        assert "OSRS" in result

    @pytest.mark.anyio
    async def test_alias_substitution_finds_page_after_initial_miss(self, monkeypatch):
        # First search ("Masterwork gauntlets") → empty. Aliased search
        # ("Masterwork melee gloves") → hit. Parse returns the body.
        async def fake_http_get(url, params=None, timeout=10.0):
            if params.get("action") == "query":
                if "gauntlets" in params["gsrsearch"]:
                    return _search_pages()
                if "melee gloves" in params["gsrsearch"]:
                    return _search_pages("Masterwork melee gloves")
            if params.get("action") == "parse":
                return _parse_html("<p>Top-tier melee gloves with set bonus.</p>")
            raise AssertionError(f"unexpected params: {params}")

        monkeypatch.setattr("rs_mcp_server.tools.wiki.http_get", fake_http_get)
        result = await search_wiki("Masterwork gauntlets", "rs3")
        assert "**Masterwork melee gloves**" in result
        assert "Top-tier melee gloves with set bonus." in result

    @pytest.mark.anyio
    async def test_template_rendered_body_replaces_extract(self, monkeypatch):
        # parse response simulates a page with a template-rendered set-bonus
        # section that the old extracts API would have dropped to just the header.
        html_body = (
            '<div class="mw-parser-output">'
            '<h2><span id="Set_bonus">Set bonus</span></h2>'
            '<p>Wearing the full set grants a 12% damage reduction against demons.</p>'
            '</div>'
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            if params.get("action") == "query":
                return _search_pages("Trimmed masterwork armour")
            if params.get("action") == "parse":
                return _parse_html(html_body)
            raise AssertionError(f"unexpected params: {params}")

        monkeypatch.setattr("rs_mcp_server.tools.wiki.http_get", fake_http_get)
        result = await search_wiki("Trimmed masterwork", "rs3")
        assert "Set bonus" in result
        assert "12% damage reduction against demons" in result


class TestExpandAliases:
    def test_returns_original_only_when_no_match(self):
        assert expand_aliases("Rune scimitar") == ["Rune scimitar"]

    def test_substitutes_whole_word_only(self):
        # "Masterwork gauntlets" contains the whole word "gauntlets" → substituted.
        forms = expand_aliases("Masterwork gauntlets")
        assert forms[0] == "Masterwork gauntlets"
        assert "Masterwork melee gloves" in forms

        # "Helmet" contains "helm" only as a prefix, not a whole word → no substitution.
        assert expand_aliases("Helmet") == ["Helmet"]

        # "Adamant helm" → whole-word "helm" substituted to "helmet".
        adam = expand_aliases("Adamant helm")
        assert adam[0] == "Adamant helm"
        assert "Adamant helmet" in adam
