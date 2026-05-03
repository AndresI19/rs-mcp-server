"""Tests for the get_game_setting MCP tool (issue #47)."""
import pytest

from rs_mcp_server.tools.settings import (
    _match_setting,
    _parse_settings_html,
    get_game_setting,
)


_FIXTURE_HTML = """
<h2 id="Display">Display</h2>
<h3 id="Skills">Skills</h3>
<table class="wikitable">
<tr><th>Setting</th><th>Function</th></tr>
<tr><td>Roof removal</td><td>When enabled, removes building roofs in the game world to improve visibility.</td></tr>
<tr><td>XP counters</td><td>Toggles whether floating XP drops appear when you gain experience.</td></tr>
</table>
<h3 id="Audio_settings">Audio settings</h3>
<table class="wikitable">
<tr><th>Setting</th><th>Function</th></tr>
<tr><td>Master volume</td><td>Controls the overall audio level for music, sound effects, and ambience.</td></tr>
<tr><td>Music volume</td><td>Adjusts background music volume independently from sound effects.</td></tr>
</table>
<h2 id="Controls">Controls</h2>
<table class="wikitable">
<tr><th>Setting</th><th>Function</th></tr>
<tr><td>Mouse camera</td><td>Hold the right mouse button to rotate the camera.</td></tr>
</table>
"""


def _parse_response(html_text: str) -> dict:
    return {"parse": {"text": html_text}}


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseSettingsHtml:
    def test_extracts_all_data_rows(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        assert len(rows) == 5
        names = [r["name"] for r in rows]
        assert "Roof removal" in names
        assert "Master volume" in names
        assert "Mouse camera" in names

    def test_section_and_subsection_tracked(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        roof = next(r for r in rows if r["name"] == "Roof removal")
        assert roof["section"] == "Display"
        assert roof["subsection"] == "Skills"
        master = next(r for r in rows if r["name"] == "Master volume")
        assert master["section"] == "Display"
        assert master["subsection"] == "Audio settings"
        mouse = next(r for r in rows if r["name"] == "Mouse camera")
        assert mouse["section"] == "Controls"
        assert mouse["subsection"] == ""

    def test_anchor_prefers_subsection(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        roof = next(r for r in rows if r["name"] == "Roof removal")
        assert roof["anchor"] == "Skills"
        mouse = next(r for r in rows if r["name"] == "Mouse camera")
        assert mouse["anchor"] == "Controls"

    def test_header_row_skipped(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        assert all("Setting" != r["name"] for r in rows)

    def test_html_entities_decoded(self):
        html_text = '<h2 id="X">X</h2><table class="wikitable"><tr><td>Spaces &amp; tabs</td><td>Text with &nbsp; entity.</td></tr></table>'
        rows = _parse_settings_html(html_text)
        assert rows[0]["name"] == "Spaces & tabs"
        assert "Text with" in rows[0]["description"]

    def test_no_tables_returns_empty(self):
        assert _parse_settings_html("<p>just prose</p>") == []


# ---------------------------------------------------------------------------
# Matcher tests
# ---------------------------------------------------------------------------

class TestMatchSetting:
    def test_exact_match(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        kind, payload = _match_setting("Roof removal", rows)
        assert kind == "exact"
        assert payload["name"] == "Roof removal"

    def test_case_insensitive_exact_match(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        kind, payload = _match_setting("roof REMOVAL", rows)
        assert kind == "exact"
        assert payload["name"] == "Roof removal"

    def test_substring_did_you_mean(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        kind, payload = _match_setting("volume", rows)
        assert kind == "did_you_mean"
        names = [r["name"] for r in payload]
        assert "Master volume" in names
        assert "Music volume" in names

    def test_description_fallback(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        kind, payload = _match_setting("XP drops", rows)
        assert kind == "description_hits"
        assert any(r["name"] == "XP counters" for r in payload)

    def test_no_match(self):
        rows = _parse_settings_html(_FIXTURE_HTML)
        kind, payload = _match_setting("zzznotasettingzzz", rows)
        assert kind == "none"
        assert payload is None


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------

class TestGetGameSetting:
    @pytest.mark.anyio
    async def test_exact_match_returns_full_block(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _parse_response(_FIXTURE_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.settings.http_get", fake_http_get)
        result = await get_game_setting("Roof removal", "osrs")
        assert "**Roof removal**" in result
        assert "OSRS Wiki" in result
        assert "Display > Skills" in result
        assert "When enabled" in result
        assert "/Settings#Skills" in result

    @pytest.mark.anyio
    async def test_did_you_mean_for_partial(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _parse_response(_FIXTURE_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.settings.http_get", fake_http_get)
        result = await get_game_setting("volume", "rs3")
        assert "Did you mean" in result
        assert "Master volume" in result
        assert "Music volume" in result
        assert "RS3 Wiki" in result

    @pytest.mark.anyio
    async def test_description_fallback_message(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _parse_response(_FIXTURE_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.settings.http_get", fake_http_get)
        result = await get_game_setting("XP drops", "osrs")
        assert "appears in these descriptions" in result
        assert "XP counters" in result

    @pytest.mark.anyio
    async def test_no_match_returns_browse_message(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _parse_response(_FIXTURE_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.settings.http_get", fake_http_get)
        result = await get_game_setting("zzznotasettingzzz", "osrs")
        assert "No matching setting" in result
        assert "Browse the full list" in result


class TestGetGameSettingValidation:
    @pytest.mark.anyio
    async def test_unknown_game_returns_error(self):
        result = await get_game_setting("Master volume", "invalidgame")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_empty_name_returns_error(self):
        result = await get_game_setting("", "osrs")
        assert "No setting name provided" in result

    @pytest.mark.anyio
    async def test_whitespace_name_returns_error(self):
        result = await get_game_setting("   ", "osrs")
        assert "No setting name provided" in result
