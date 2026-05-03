"""Tests for the solve_clue MCP tool (issue #50)."""
import pytest

from rs_mcp_server.tools.clues import (
    _match_clues,
    _parse_clue_html,
    solve_clue,
)


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

_ANAGRAM_HTML = """
<h3 id="Medium_Anagrams">Medium Anagrams</h3>
<table class="wikitable">
<tr><th>Anagram</th><th>Solution</th><th>Location</th></tr>
<tr><td>OK CO</td><td>Cook</td><td>Lumbridge Castle kitchen</td></tr>
<tr><td>GOOR KARP</td><td>Karpov</td><td>Brimhaven Agility Arena</td></tr>
</table>
<h3 id="Hard_Anagrams">Hard Anagrams</h3>
<table class="wikitable">
<tr><th>Anagram</th><th>Solution</th><th>Location</th></tr>
<tr><td>I EVEN</td><td>Vinny</td><td>The Mage Arena</td></tr>
</table>
"""

_CRYPTIC_HTML = """
<h3 id="Easy_Cryptic_clues">Easy Cryptic clues</h3>
<table class="wikitable">
<tr><th>Clue</th><th>Solution</th><th>Location</th></tr>
<tr><td>Talk to the bartender of the Rusty Anchor.</td><td>Talk to the bartender</td><td>The Rusty Anchor inn in Port Sarim</td></tr>
</table>
"""

_EMOTE_HTML = """
<h3 id="Medium_Emote_clues">Medium Emote clues</h3>
<table class="wikitable">
<tr><th>Clue</th><th>Items</th><th>Location</th></tr>
<tr>
  <td>Headbang in Nardah while wearing desert clothing.</td>
  <td><img alt="Desert robe"/><img alt="Desert top"/></td>
  <td>Nardah, north-east of the well</td>
</tr>
</table>
"""

_CIPHER_HTML = """
<h3 id="Medium_Ciphers">Medium Ciphers</h3>
<table class="wikitable">
<tr><th>Cipher</th><th>Decoded</th><th>Location</th></tr>
<tr><td>ESBZOPS QJH QFO</td><td>DRAYNOR PIG PEN</td><td>Draynor Village, north of the market</td></tr>
</table>
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseAnagramHtml:
    def test_extracts_two_tier_sections(self):
        rows = _parse_clue_html(_ANAGRAM_HTML, "anagram")
        assert len(rows) == 3
        tiers = {r["tier"] for r in rows}
        assert tiers == {"medium", "hard"}

    def test_anagram_fields(self):
        rows = _parse_clue_html(_ANAGRAM_HTML, "anagram")
        cook = next(r for r in rows if r["clue_text"] == "OK CO")
        assert cook["solution"] == "Cook"
        assert "Lumbridge" in cook["location"]
        assert cook["tier"] == "medium"

    def test_anagram_strips_rs3_prefix(self):
        html = (
            '<h3 id="Medium_anagrams">Medium anagrams</h3>'
            '<table class="wikitable">'
            "<tr><th>X</th><th>Y</th><th>Z</th></tr>"
            "<tr><td>This anagram reveals who to speak to next: OK CO</td><td>Cook</td><td>Lumbridge</td></tr>"
            "</table>"
        )
        rows = _parse_clue_html(html, "anagram")
        assert rows[0]["clue_text"] == "OK CO"


class TestParseCrypticHtml:
    def test_extracts_clue_solution_location(self):
        rows = _parse_clue_html(_CRYPTIC_HTML, "cryptic")
        assert len(rows) == 1
        r = rows[0]
        assert "Rusty Anchor" in r["clue_text"]
        assert "bartender" in r["solution"]
        assert "Port Sarim" in r["location"]
        assert r["tier"] == "easy"


class TestParseEmoteHtml:
    def test_extracts_items_from_img_alt(self):
        rows = _parse_clue_html(_EMOTE_HTML, "emote")
        assert len(rows) == 1
        r = rows[0]
        assert "Headbang" in r["clue_text"]
        assert "Desert robe" in r["items"]
        assert "Desert top" in r["items"]
        assert "Nardah" in r["location"]
        assert r["tier"] == "medium"


class TestParseCipherHtml:
    def test_extracts_cipher_decoded_location(self):
        rows = _parse_clue_html(_CIPHER_HTML, "cipher")
        assert len(rows) == 1
        r = rows[0]
        assert r["clue_text"] == "ESBZOPS QJH QFO"
        assert r["decoded"] == "DRAYNOR PIG PEN"
        assert "Draynor" in r["location"]


class TestParseSkipsTablesOutsideTier:
    def test_table_before_first_tier_heading_skipped(self):
        html = '<table class="wikitable"><tr><td>X</td><td>Y</td></tr></table>'
        assert _parse_clue_html(html, "anagram") == []


# ---------------------------------------------------------------------------
# Matcher tests
# ---------------------------------------------------------------------------

class TestMatchClues:
    def test_exact_match(self):
        rows = _parse_clue_html(_ANAGRAM_HTML, "anagram")
        kind, payload = _match_clues("OK CO", rows)
        assert kind == "exact"
        assert payload["solution"] == "Cook"

    def test_case_insensitive_match(self):
        rows = _parse_clue_html(_ANAGRAM_HTML, "anagram")
        kind, payload = _match_clues("ok co", rows)
        assert kind == "exact"

    def test_substring_did_you_mean(self):
        rows = _parse_clue_html(_ANAGRAM_HTML, "anagram")
        kind, payload = _match_clues("KARP", rows)
        assert kind == "did_you_mean"
        assert any(r["clue_text"] == "GOOR KARP" for r in payload)

    def test_no_match(self):
        rows = _parse_clue_html(_ANAGRAM_HTML, "anagram")
        kind, payload = _match_clues("zzznosuchclue", rows)
        assert kind == "none"


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------

def _parse_response(html_text: str) -> dict:
    return {"parse": {"text": html_text}}


class TestSolveClue:
    @pytest.mark.anyio
    async def test_format_hint_narrows_search(self, monkeypatch):
        calls = []

        async def fake_http_get(url, params=None, timeout=10.0):
            calls.append((params or {}).get("page"))
            return _parse_response(_ANAGRAM_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.clues.http_get", fake_http_get)
        result = await solve_clue("OK CO", "osrs", clue_format="anagram")
        assert "**OK CO**" in result
        assert "Cook" in result
        assert "Medium anagram" in result
        assert len(calls) == 1  # only anagram page fetched

    @pytest.mark.anyio
    async def test_no_format_hint_fetches_all(self, monkeypatch):
        calls = []

        async def fake_http_get(url, params=None, timeout=10.0):
            calls.append((params or {}).get("page"))
            return _parse_response(_ANAGRAM_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.clues.http_get", fake_http_get)
        result = await solve_clue("OK CO", "osrs")
        assert "Cook" in result
        # OSRS supports all 4 formats so 4 fetches expected
        assert len(calls) == 4

    @pytest.mark.anyio
    async def test_tier_filter_narrows_results(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _parse_response(_ANAGRAM_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.clues.http_get", fake_http_get)
        result = await solve_clue("I EVEN", "osrs", clue_format="anagram", tier="hard")
        assert "Vinny" in result

        result = await solve_clue("I EVEN", "osrs", clue_format="anagram", tier="medium")
        # Wrong tier filter → no exact match within filtered set
        assert "No matching clue" in result

    @pytest.mark.anyio
    async def test_did_you_mean_for_partial(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _parse_response(_ANAGRAM_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.clues.http_get", fake_http_get)
        result = await solve_clue("karp", "osrs", clue_format="anagram")
        assert "Did you mean" in result
        assert "GOOR KARP" in result

    @pytest.mark.anyio
    async def test_no_match_message(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _parse_response(_ANAGRAM_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.clues.http_get", fake_http_get)
        result = await solve_clue("zzznosuchclue", "osrs", clue_format="anagram")
        assert "No matching clue" in result

    @pytest.mark.anyio
    async def test_rs3_cipher_unsupported(self):
        result = await solve_clue("anything", "rs3", clue_format="cipher")
        assert "doesn't have a documented cipher clue dataset" in result


class TestSolveClueValidation:
    @pytest.mark.anyio
    async def test_unknown_game(self):
        result = await solve_clue("anything", "invalid")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_unknown_format(self):
        result = await solve_clue("anything", "osrs", clue_format="bogus")
        assert "Unknown clue_format" in result

    @pytest.mark.anyio
    async def test_unknown_tier(self):
        result = await solve_clue("anything", "osrs", tier="legendary")
        assert "Unknown tier" in result

    @pytest.mark.anyio
    async def test_empty_text(self):
        result = await solve_clue("", "osrs")
        assert "No clue text provided" in result
