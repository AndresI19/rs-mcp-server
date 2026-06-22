"""Tests for the get_item_drop_sources MCP tool (issue #58)."""
import pytest

from rs_mcp_server import cache as _cache_mod
from rs_mcp_server.tools.drops import get_item_drop_sources


@pytest.fixture(autouse=True)
def _reset_cache():
    _cache_mod._store.clear()
    yield


def _wiki_parse(title: str, body_html: str) -> dict:
    return {"parse": {"title": title, "text": body_html}}


def _table_html(rows_html: str) -> str:
    return (
        '<div><table class="wikitable sortable filterable item-drops align-center-2">'
        '<tbody>'
        '<tr><th>Source</th><th>Level</th><th>Quantity</th><th>Rarity</th></tr>'
        f'{rows_html}'
        '</tbody></table></div>'
    )


def _drops_row(source: str, level: str | None, quantity: str, rarity: str, version: str = "") -> str:
    """Build one rendered <tr> matching the wiki's item-drops table schema."""
    version_span = f'<span class="beast-version">{version}</span>' if version else ""
    if level is None:
        level_td = '<td class="table-na" data-sort-value="0">N/A</td>'
    else:
        level_td = f'<td data-sort-value="{level}">{level}</td>'
    rarity_td = f'<td data-sort-value="1"><span data-drop-fraction="{rarity}" data-drop-percent="0.5">{rarity}</span></td>'
    return (
        f'<tr><td><a href="/w/{source.replace(" ", "_")}" title="{source}">{source}{version_span}</a></td>'
        f'{level_td}'
        f'<td data-sort-value="1">{quantity}</td>'
        f'{rarity_td}</tr>'
    )


class TestGetItemDropSources:
    @pytest.mark.anyio
    async def test_happy_path_caps_at_three_with_overflow_note(self, monkeypatch):
        rows = (
            _drops_row("Abyssal demon", "124", "1", "1/512")
            + _drops_row("Greater demon", "92", "1", "1/2048")
            + _drops_row("Lesser demon", "82", "1", "1/4096")
            + _drops_row("Imp", "7", "1", "1/8192")
        )
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_parse("Abyssal whip", _table_html(rows))

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", fake_http_get)
        result = await get_item_drop_sources("Abyssal whip", "osrs")

        assert "**Drop sources for Abyssal whip** (OSRS Wiki)" in result
        assert "https://oldschool.runescape.wiki/w/Abyssal_whip" in result
        assert "**Top sources:**" in result
        assert "1. Abyssal demon — 1/512 from a level-124 monster, qty 1" in result
        assert "2. Greater demon — 1/2048 from a level-92 monster, qty 1" in result
        assert "3. Lesser demon — 1/4096 from a level-82 monster, qty 1" in result
        assert "Imp" not in result
        assert "(1 more source — common loot." in result

    @pytest.mark.anyio
    async def test_two_sources_no_overflow_line(self, monkeypatch):
        rows = (
            _drops_row("Goblin", "2", "1", "1/4")
            + _drops_row("Goblin guard", "42", "1", "1/8")
        )
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_parse("Bones", _table_html(rows))

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", fake_http_get)
        result = await get_item_drop_sources("Bones", "rs3")

        assert "1. Goblin — 1/4 from a level-2 monster, qty 1" in result
        assert "2. Goblin guard — 1/8 from a level-42 monster, qty 1" in result
        assert "common loot" not in result
        assert "(RS3 Wiki)" in result

    @pytest.mark.anyio
    async def test_no_item_drops_table_returns_no_sources_message(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_parse("Bread", '<div><p>Bread is a basic food item.</p></div>')

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", fake_http_get)
        result = await get_item_drop_sources("Bread", "osrs")

        assert "No drop sources recorded for 'Bread' on the OSRS Wiki." in result
        assert "https://oldschool.runescape.wiki/w/Bread" in result

    @pytest.mark.anyio
    async def test_non_combat_source_renders_as_drop_not_level(self, monkeypatch):
        rows = _drops_row("Unsired", None, "1", "12/128")
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_parse("Abyssal whip", _table_html(rows))

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", fake_http_get)
        result = await get_item_drop_sources("Abyssal whip", "osrs")

        assert "1. Unsired — 12/128 drop, qty 1" in result
        assert "level-" not in result

    @pytest.mark.anyio
    async def test_version_suffix_renders_in_parens(self, monkeypatch):
        rows = _drops_row("Abyssal demon", "124", "1", "1/512", version="Wilderness Slayer Cave")
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_parse("Abyssal whip", _table_html(rows))

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", fake_http_get)
        result = await get_item_drop_sources("Abyssal whip", "osrs")

        assert "1. Abyssal demon (Wilderness Slayer Cave) — 1/512 from a level-124 monster, qty 1" in result

    @pytest.mark.anyio
    async def test_missing_page_returns_not_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return {"error": {"code": "missingtitle", "info": "page does not exist"}}

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", fake_http_get)
        result = await get_item_drop_sources("zzznotanitemzzz", "rs3")

        assert result == "Item 'zzznotanitemzzz' not found on the RS3 Wiki."

    @pytest.mark.anyio
    async def test_second_call_hits_cache(self, monkeypatch):
        rows = _drops_row("Cow", "2", "1", "1/2")
        call_count = {"n": 0}
        async def fake_http_get(url, params=None, timeout=10.0):
            call_count["n"] += 1
            return _wiki_parse("Bones", _table_html(rows))

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", fake_http_get)
        first = await get_item_drop_sources("Bones", "rs3")
        second = await get_item_drop_sources("Bones", "rs3")

        assert call_count["n"] == 1
        assert first == second

    @pytest.mark.anyio
    async def test_unknown_game_rejected(self, monkeypatch):
        result = await get_item_drop_sources("Abyssal whip", "rs2")
        assert "Unknown game 'rs2'" in result

    @pytest.mark.anyio
    async def test_non_http_error_is_not_masked(self, monkeypatch):
        # The fetch only swallows httpx errors now — a programming bug (e.g. a
        # ValueError) must surface, not be hidden behind a misleading "not found".
        async def boom(url, params=None, timeout=10.0):
            raise ValueError("parsing bug")

        monkeypatch.setattr("rs_mcp_server.tools.drops.http_get", boom)
        with pytest.raises(ValueError):
            await get_item_drop_sources("Abyssal whip", "rs3")
