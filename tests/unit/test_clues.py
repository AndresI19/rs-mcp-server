"""Tests for the solve_clue MCP tool (issue #50)."""

import pytest

from rs_mcp_server.tools.clues import (
    _detect_visual,
    _match_clues,
    _parse_clue_html,
    _render_visual,
    _resolve_coordinate,
    normalize_coordinate,
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

# Challenge scrolls are tier-less: one flat NPC|Question|Answer table, no <h3> sections.
_CHALLENGE_HTML = """
<table class="wikitable">
<tr><th>NPC</th><th>Question</th><th>Answer</th></tr>
<tr><td>Ironman tutor</td><td>How many snakeskins are needed?</td><td>666</td></tr>
<tr><td>Gnome ball referee</td><td>How many points is a goal worth?</td><td>10</td></tr>
</table>
"""

# RS3 simple clues share the cryptic shape (clue | solution | location), tier in <h2>.
_SIMPLE_HTML = """
<h2 id="Easy_simple_clues">Easy simple clues</h2>
<table class="wikitable">
<tr><th>Cryptic</th><th>Solution</th><th>Location</th></tr>
<tr><td>Search the chest in the Duke's bedroom.</td><td>In Lumbridge Castle, 1st floor</td><td>Lumbridge Castle</td></tr>
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


class TestParseChallengeHtml:
    def test_tierless_questions_extracted(self):
        rows = _parse_clue_html(_CHALLENGE_HTML, "challenge")
        assert len(rows) == 2
        r = next(x for x in rows if "snakeskins" in x["clue_text"])
        assert r["answer"] == "666"
        assert r["npc"] == "Ironman tutor"
        assert r["tier"] == ""  # challenge pages carry no tier
        assert r["format"] == "challenge"

    def test_question_is_the_clue_text(self):
        # The matchable clue_text must be the question (col 1), not the NPC (col 0).
        rows = _parse_clue_html(_CHALLENGE_HTML, "challenge")
        assert all(r["clue_text"].startswith("How many") for r in rows)


class TestParseSimpleHtml:
    def test_simple_clue_extracted(self):
        rows = _parse_clue_html(_SIMPLE_HTML, "simple")
        assert len(rows) == 1
        r = rows[0]
        assert "chest" in r["clue_text"]
        assert r["solution"] == "In Lumbridge Castle, 1st floor"
        assert r["tier"] == "easy"
        assert r["format"] == "simple"


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
        # OSRS supports all 5 live formats (anagram/cryptic/emote/cipher/challenge)
        assert len(calls) == 5

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


# ---------------------------------------------------------------------------
# Coordinates (baked dataset — these tests never touch the live wiki)
# ---------------------------------------------------------------------------


class TestNormalizeCoordinate:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("04 degrees 13 minutes south, 16 degrees 25 minutes east", "04.13S,16.25E"),
            ("00 degrees 05 minutes south, 01 degrees 13 minutes east", "00.05S,01.13E"),
            ("00 degrees 00 minutes north 07 degrees 13 minutes west", "00.00N,07.13W"),
            ("AN EARL", None),
            ("Talk to the bartender of the Rusty Anchor.", None),
        ],
    )
    def test_normalize(self, text, expected):
        assert normalize_coordinate(text) == expected


class TestResolveCoordinate:
    def test_resolves_known_coordinate_from_baked_data(self):
        # 00.05S,01.13E is in both committed datasets; resolution is purely local.
        out = _resolve_coordinate(
            "00 degrees 05 minutes south, 01 degrees 13 minutes east", "rs3", "RS3"
        )
        assert out is not None
        assert "Medium coordinate" in out
        assert "Location:" in out  # RS3 carries a text location

    def test_non_coordinate_returns_none(self):
        # None signals "not a coordinate" so the caller falls through to text formats.
        assert _resolve_coordinate("AN EARL", "osrs", "OSRS") is None

    def test_unknown_coordinate_points_to_guide(self):
        out = _resolve_coordinate(
            "89 degrees 59 minutes north, 89 degrees 59 minutes west", "osrs", "OSRS"
        )
        assert out is not None and "not in the OSRS dataset" in out


class TestDetectVisual:
    def test_map_detected(self):
        v = _detect_visual("I have a hand-drawn map", "osrs")
        assert v is not None and v[0] == "map"

    def test_compass_is_rs3_only(self):
        assert _detect_visual("compass clue", "rs3")[0] == "compass"
        assert _detect_visual("compass clue", "osrs") is None

    def test_specific_type_beats_generic_puzzle(self):
        # "lockbox" must win over the generic "puzzle" catch-all.
        assert _detect_visual("lockbox puzzle", "rs3")[0] == "lockbox"

    def test_plain_text_clue_not_visual(self):
        assert _detect_visual("Talk to the bartender of the Rusty Anchor", "osrs") is None

    def test_compass_is_self_solved_no_link(self):
        # Compass is genuinely not supported — solved in-game, so no guide link.
        vtype, info = _detect_visual("compass clue", "rs3")
        assert vtype == "compass" and info.get("in_game")
        rendered = _render_visual(vtype, info, "RS3")
        assert "http" not in rendered
        assert "arrow" in rendered.lower()
