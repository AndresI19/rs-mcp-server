"""Unit tests for tools/hiscores.py parsing helpers (issue #18) and the get_player_stats tool (issue #28)."""
import httpx
import pytest

from rs_mcp_server.tools.hiscores import _OSRS_SKILLS, _RS3_SKILLS, _fmt_rank, _format_stats, get_player_stats


# ── _format_stats ─────────────────────────────────────────────────────────────

class TestFormatStats:
    def test_basic_osrs_csv(self):
        # rank,level,xp on each line; first row is Overall
        csv = "\n".join([
            "100,2277,200000000",       # Overall
            "10,99,13034431",            # Attack
            "20,99,13034431",            # Defence
        ])
        result = _format_stats("Lynx Titan", "osrs", csv, _OSRS_SKILLS)
        assert "**Lynx Titan** (OSRS Hiscores)" in result
        assert "Total level: 2,277" in result
        assert "Attack" in result
        assert "Defence" in result

    def test_basic_rs3_csv(self):
        csv = "\n".join(["1,3000,2000000000"] + ["10,99,13000000"] * 29)
        result = _format_stats("Zezima", "rs3", csv, _RS3_SKILLS)
        assert "**Zezima** (RS3 Hiscores)" in result
        assert "Total level: 3,000" in result

    def test_csv_shorter_than_skills_tuple(self):
        # Only Overall + Attack provided, rest of skills tuple has no data
        csv = "100,1500,5000000\n10,80,2000000"
        result = _format_stats("PartialPlayer", "osrs", csv, _OSRS_SKILLS)
        assert "Total level: 1,500" in result
        assert "Attack" in result
        # Subsequent skills shouldn't appear
        assert "Defence" not in result

    def test_extra_columns_ignored(self):
        # Real hiscores CSV has rank,level,xp; we only use the first two columns
        csv = "100,2277,200000000,extra,fields\n10,99,13034431"
        result = _format_stats("Test", "osrs", csv, _OSRS_SKILLS)
        assert "Total level: 2,277" in result

    def test_malformed_row_skipped_not_crashed(self):
        # Bug fix: previously this would crash on int("not_a_number")
        csv = "\n".join([
            "100,2277,200000000",       # Overall — valid
            "garbage,oops,xx",           # malformed — must be skipped
            "20,99,13034431",            # Attack — valid (now in position 1 of skills)
        ])
        # Should NOT raise
        result = _format_stats("Test", "osrs", csv, _OSRS_SKILLS)
        assert "Total level: 2,277" in result

    def test_all_rows_malformed_returns_no_data_message(self):
        csv = "garbage\nmore garbage\nstill garbage"
        result = _format_stats("Test", "osrs", csv, _OSRS_SKILLS)
        assert "No usable hiscores data" in result
        assert "**Test**" in result

    def test_empty_csv_returns_no_data_message(self):
        result = _format_stats("Test", "osrs", "", _OSRS_SKILLS)
        assert "No usable hiscores data" in result

    def test_short_row_skipped(self):
        # Row with fewer than 2 columns is skipped per len(parts) < 2 guard
        csv = "100,2277\nincomplete\n10,99"
        result = _format_stats("Test", "osrs", csv, _OSRS_SKILLS)
        assert "Total level: 2,277" in result


# ── _fmt_rank ─────────────────────────────────────────────────────────────────

class TestFmtRank:
    def test_positive_rank_with_comma(self):
        assert _fmt_rank(1234) == "1,234"
        assert _fmt_rank(1) == "1"
        assert _fmt_rank(1000000) == "1,000,000"

    def test_zero_rank_dash(self):
        assert _fmt_rank(0) == "—"

    def test_large_rank(self):
        assert _fmt_rank(9999999) == "9,999,999"


# ── get_player_stats end-to-end ───────────────────────────────────────────────

class TestGetPlayerStats:
    @pytest.mark.anyio
    async def test_osrs_happy(self, monkeypatch):
        csv = "\n".join([
            "100,2277,200000000",
            "10,99,13034431",
            "20,99,13034431",
        ])

        async def fake_http_get_text(url, params=None, timeout=10.0):
            return csv

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get_text", fake_http_get_text)
        result = await get_player_stats("Lynx Titan", "osrs")
        assert "**Lynx Titan** (OSRS Hiscores)" in result
        assert "Total level: 2,277" in result

    @pytest.mark.anyio
    async def test_rs3_happy(self, monkeypatch):
        csv = "\n".join(["1,3000,2000000000"] + ["10,99,13000000"] * 29)

        async def fake_http_get_text(url, params=None, timeout=10.0):
            return csv

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get_text", fake_http_get_text)
        result = await get_player_stats("Zezima", "rs3")
        assert "**Zezima** (RS3 Hiscores)" in result
        assert "Total level: 3,000" in result

    @pytest.mark.anyio
    async def test_404_returns_not_found_string(self, monkeypatch):
        async def fake_http_get_text(url, params=None, timeout=10.0):
            response = httpx.Response(404)
            raise httpx.HTTPStatusError(
                "404 Not Found",
                request=httpx.Request("GET", url),
                response=response,
            )

        monkeypatch.setattr("rs_mcp_server.tools.hiscores.http_get_text", fake_http_get_text)
        result = await get_player_stats("ghostplayer", "osrs")
        assert result == "Player 'ghostplayer' not found on OSRS Hiscores."
