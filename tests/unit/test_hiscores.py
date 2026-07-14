"""Unit tests for tools/hiscores.py (issues #18, #28, #59)."""

import httpx
import pytest

from rs_mcp_server.tools.hiscores import _fmt_rank, _format_stats, get_player_stats


def _data(skills: list[dict], activities: list[dict] | None = None) -> dict:
    return {"skills": skills, "activities": activities or []}


def _skill(name: str, rank: int = 100, level: int = 99, xp: int = 13_034_431) -> dict:
    return {"name": name, "rank": rank, "level": level, "xp": xp}


def _activity(name: str, rank: int = -1, score: int = -1) -> dict:
    return {"name": name, "rank": rank, "score": score}


# ── _format_stats ─────────────────────────────────────────────────────────────


class TestFormatStats:
    def test_basic_osrs(self):
        data = _data(
            [
                _skill("Overall", rank=100, level=2277, xp=200_000_000),
                _skill("Attack", rank=10),
                _skill("Defence", rank=20),
            ]
        )
        result = _format_stats("Lynx Titan", "osrs", data)
        assert "**Lynx Titan** (OSRS Hiscores)" in result
        assert "Total level: 2,277" in result
        assert "Skills:" in result
        assert "Attack" in result
        assert "Defence" in result

    def test_basic_rs3(self):
        data = _data(
            [_skill("Overall", rank=1, level=3000, xp=2_000_000_000)]
            + [_skill(f"Skill{i}", level=99) for i in range(29)]
        )
        result = _format_stats("Zezima", "rs3", data)
        assert "**Zezima** (RS3 Hiscores)" in result
        assert "Total level: 3,000" in result

    def test_sailing_renders_when_present(self):
        data = _data(
            [
                _skill("Overall", rank=1, level=2278, xp=4_600_000_000),
                _skill("Attack"),
                _skill("Sailing", rank=-1, level=1, xp=0),
            ]
        )
        result = _format_stats("Lynx Titan", "osrs", data)
        assert "Sailing" in result
        assert "unranked" in result  # Sailing at rank=-1 renders the unranked marker

    def test_activities_section_renders_only_ranked_entries(self):
        data = _data(
            skills=[_skill("Overall", rank=1, level=2277)],
            activities=[
                _activity("Clue Scrolls (all)", rank=12345, score=22),
                _activity("League Points", rank=-1, score=-1),  # unranked
                _activity("Colosseum Glory", rank=500, score=10000),
            ],
        )
        result = _format_stats("Lynx Titan", "osrs", data)
        assert "Activities:" in result
        assert "Clue Scrolls (all)" in result
        assert "Colosseum Glory" in result
        # League Points is unranked → hidden
        assert "League Points" not in result

    def test_no_activities_section_when_all_unranked(self):
        data = _data(
            skills=[_skill("Overall", rank=1, level=2277)],
            activities=[
                _activity("Clue Scrolls (all)", rank=-1, score=-1),
                _activity("League Points", rank=-1, score=-1),
            ],
        )
        result = _format_stats("Test", "osrs", data)
        assert "Activities:" not in result

    def test_overall_missing_returns_no_data_message(self):
        # No "Overall" skill in the list → graceful fallback
        data = _data([_skill("Attack")])
        result = _format_stats("Test", "osrs", data)
        assert "No usable hiscores data" in result
        assert "**Test**" in result

    def test_empty_payload_returns_no_data_message(self):
        result = _format_stats("Test", "osrs", {"skills": [], "activities": []})
        assert "No usable hiscores data" in result


# ── _fmt_rank ─────────────────────────────────────────────────────────────────


class TestFmtRank:
    def test_positive_rank_with_comma(self):
        assert _fmt_rank(1234) == "1,234"
        assert _fmt_rank(1) == "1"
        assert _fmt_rank(1_000_000) == "1,000,000"

    def test_zero_rank_dash(self):
        assert _fmt_rank(0) == "—"

    def test_negative_rank_dash(self):
        assert _fmt_rank(-1) == "—"


# ── get_player_stats end-to-end ───────────────────────────────────────────────


class TestGetPlayerStats:
    @pytest.mark.anyio
    async def test_osrs_happy(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _data(
                [
                    _skill("Overall", rank=100, level=2277, xp=200_000_000),
                    _skill("Attack", rank=10),
                    _skill("Defence", rank=20),
                ]
            )

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get", fake_http_get)
        result = await get_player_stats("Lynx Titan", "osrs")
        assert "**Lynx Titan** (OSRS Hiscores)" in result
        assert "Total level: 2,277" in result

    @pytest.mark.anyio
    async def test_rs3_happy(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _data(
                [_skill("Overall", rank=1, level=3000, xp=2_000_000_000)]
                + [_skill(f"Skill{i}") for i in range(29)]
            )

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get", fake_http_get)
        result = await get_player_stats("Zezima", "rs3")
        assert "**Zezima** (RS3 Hiscores)" in result
        assert "Total level: 3,000" in result

    @pytest.mark.anyio
    async def test_404_returns_privacy_aware_message(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            response = httpx.Response(404)
            raise httpx.HTTPStatusError(
                "404 Not Found",
                request=httpx.Request("GET", url),
                response=response,
            )

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get", fake_http_get)
        result = await get_player_stats("ghostplayer", "osrs")
        assert "No public hiscores for 'ghostplayer'" in result
        assert "OSRS" in result
        assert "may not exist" in result
        assert "hidden in privacy settings" in result

    @pytest.mark.anyio
    async def test_request_error_degrades_gracefully(self, monkeypatch):
        # A transient network error (timeout/connection) should return a friendly
        # message rather than crashing the tool.
        async def fake_http_get(url, params=None, timeout=10.0):
            raise httpx.ConnectTimeout("timed out", request=httpx.Request("GET", url))

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get", fake_http_get)
        result = await get_player_stats("anyone", "rs3")
        assert "temporarily unavailable" in result
        assert "RS3" in result

    @pytest.mark.anyio
    async def test_non_404_status_degrades_gracefully(self, monkeypatch):
        # A non-404 HTTP error (e.g. 503 outage, 403) must not crash the tool.
        async def fake_http_get(url, params=None, timeout=10.0):
            raise httpx.HTTPStatusError(
                "503", request=httpx.Request("GET", url), response=httpx.Response(503)
            )

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get", fake_http_get)
        result = await get_player_stats("anyone", "osrs")
        assert "Couldn't retrieve" in result
        assert "503" in result


class TestUsernameValidation:
    @pytest.mark.anyio
    async def test_empty_username(self):
        assert "provide a player username" in await get_player_stats("", "osrs")

    @pytest.mark.anyio
    async def test_whitespace_username(self):
        assert "provide a player username" in await get_player_stats("   ", "osrs")

    @pytest.mark.anyio
    async def test_invalid_chars_rejected(self):
        assert "isn't a valid RuneScape name" in await get_player_stats("<script>", "osrs")

    @pytest.mark.anyio
    async def test_overlong_name_rejected(self):
        assert "isn't a valid RuneScape name" in await get_player_stats("ThisNameIsTooLong", "osrs")


class TestFormatStatsRobustness:
    def test_missing_numeric_fields_do_not_crash(self):
        data = {
            "skills": [{"name": "Overall", "rank": 1}, {"name": "Attack", "level": 99}],
            "activities": [{"name": "Zulrah", "rank": 5}],  # rank but no score
        }
        out = _format_stats("Tester", "osrs", data)
        assert "**Tester** (OSRS Hiscores)" in out
        assert "Attack" in out
        assert "Zulrah" in out

    def test_string_numeric_fields_coerced(self):
        data = {"skills": [{"name": "Overall", "rank": "1", "level": "2277"}], "activities": []}
        assert "Total level: 2,277" in _format_stats("Tester", "osrs", data)
