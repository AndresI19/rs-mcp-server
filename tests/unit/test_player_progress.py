"""Tests for the get_player_achievement_progress MCP tool (issue #60)."""
import httpx
import pytest

from rs_mcp_server import cache as _cache_mod
from rs_mcp_server.tools.player_progress import _format_progress, get_player_achievement_progress


@pytest.fixture(autouse=True)
def _reset_cache():
    _cache_mod._store.clear()
    yield


def _wiki_page(title: str, content: str) -> dict:
    return {
        "query": {
            "pages": [
                {
                    "title": title,
                    "revisions": [{"slots": {"main": {"content": content}}}],
                }
            ]
        }
    }


def _hiscores(activities: list[dict]) -> dict:
    return {
        "name": "test",
        "skills": [{"id": 0, "name": "Overall", "rank": 1, "level": 2277, "xp": 200_000_000}],
        "activities": activities,
    }


def _ca_wikitext(name: str, monster: str, tier: str = "Easy") -> str:
    return (
        "{{Infobox Combat Achievement\n"
        f"|description = Kill {monster} with style.\n"
        f"|tier = {tier}\n"
        "|type = Mechanical\n"
        f"|monster = {monster}\n"
        "|members = Yes\n"
        "|release = 1 January 2026\n"
        "}}"
    )


_DIARY_WIKITEXT = (
    "{{Infobox Achievement Diary\n"
    "|areas = Falador, Mining Guild\n"
    "|members = Yes\n"
    "|taskmasters = Sir Rebrum\n"
    "|reward = Falador shield\n"
    "|release = 1 February 2010\n"
    "}}"
)

_RS3_ACH_WIKITEXT = (
    "{{Infobox Achievement\n"
    "|description = Cast Lunar magic.\n"
    "|score = 10\n"
    "|maincategory = Magic\n"
    "|subcategory = Spellbooks\n"
    "|requirements = 65 Magic\n"
    "|members = Yes\n"
    "|release = 1 March 2009\n"
    "}}"
)


def _wiki_router(title: str, content: str):
    """Build a fake_http_get that returns the wiki page for any wiki call + the given hiscores."""
    def make(hiscores_data):
        async def fake_http_get(url, params=None, timeout=10.0):
            if "runescape.wiki" in url or "oldschool.runescape.wiki" in url:
                return _wiki_page(title, content)
            if "index_lite.json" in url:
                return hiscores_data
            raise AssertionError(f"unexpected URL: {url}")
        return fake_http_get
    return make


class TestCombatAchievement:
    @pytest.mark.anyio
    async def test_monster_kc_surfaced_when_player_ranked(self, monkeypatch):
        hiscores = _hiscores([
            {"id": 20, "name": "Abyssal Sire", "rank": 100, "score": 50},
        ])
        fake = _wiki_router("Noxious Foe", _ca_wikitext("Noxious Foe", "Abyssal Sire"))(hiscores)
        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake)
        monkeypatch.setattr("rs_mcp_server.tools.player_progress.http_get", fake)

        result = await get_player_achievement_progress("Noxious Foe", "Lynx Titan", "osrs")
        assert "**Noxious Foe**" in result
        assert "Combat Achievement" in result
        assert "Progress for Lynx Titan" in result
        assert "Abyssal Sire: 50 KCs" in result
        assert "rank 100" in result
        assert "engagement signal" in result

    @pytest.mark.anyio
    async def test_monster_unranked_shows_no_kills_message(self, monkeypatch):
        hiscores = _hiscores([
            {"id": 20, "name": "Abyssal Sire", "rank": -1, "score": -1},
        ])
        fake = _wiki_router("Noxious Foe", _ca_wikitext("Noxious Foe", "Abyssal Sire"))(hiscores)
        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake)
        monkeypatch.setattr("rs_mcp_server.tools.player_progress.http_get", fake)

        result = await get_player_achievement_progress("Noxious Foe", "Lynx Titan", "osrs")
        assert "Abyssal Sire: not yet ranked" in result

    @pytest.mark.anyio
    async def test_monster_not_in_hiscores_says_so(self, monkeypatch):
        hiscores = _hiscores([
            {"id": 20, "name": "Abyssal Sire", "rank": 100, "score": 50},
        ])
        # The CA targets "Cabbage", which is NOT in the hiscores boss list
        fake = _wiki_router("Eat the Cabbage", _ca_wikitext("Eat the Cabbage", "Cabbage"))(hiscores)
        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake)
        monkeypatch.setattr("rs_mcp_server.tools.player_progress.http_get", fake)

        result = await get_player_achievement_progress("Eat the Cabbage", "Lynx Titan", "osrs")
        assert "'Cabbage' isn't in the public hiscores boss list" in result


class TestAchievementDiary:
    @pytest.mark.anyio
    async def test_diary_says_not_in_hiscores(self, monkeypatch):
        hiscores = _hiscores([])
        fake = _wiki_router("Falador Diary", _DIARY_WIKITEXT)(hiscores)
        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake)
        monkeypatch.setattr("rs_mcp_server.tools.player_progress.http_get", fake)

        result = await get_player_achievement_progress("Falador Diary", "Lynx Titan", "osrs")
        assert "**Falador Diary**" in result
        assert "Achievement Diary" in result
        assert "Achievement Diary completion isn't in public hiscores" in result
        # No KC lookup should appear
        assert "KCs" not in result


class TestRs3Achievement:
    @pytest.mark.anyio
    async def test_rs3_says_not_in_hiscores(self, monkeypatch):
        hiscores = _hiscores([
            {"id": 2, "name": "Dominion Tower", "rank": 144, "score": 26_445_855},
        ])
        fake = _wiki_router("The Essence of Magic", _RS3_ACH_WIKITEXT)(hiscores)
        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake)
        monkeypatch.setattr("rs_mcp_server.tools.player_progress.http_get", fake)

        result = await get_player_achievement_progress("The Essence of Magic", "Zezima", "rs3")
        assert "**The Essence of Magic**" in result
        assert "Per-task achievement completion isn't in public hiscores" in result


class TestPlayer404:
    @pytest.mark.anyio
    async def test_privacy_message_appended_under_achievement_info(self, monkeypatch):
        async def fake(url, params=None, timeout=10.0):
            if "runescape.wiki" in url or "oldschool.runescape.wiki" in url:
                return _wiki_page("Noxious Foe", _ca_wikitext("Noxious Foe", "Abyssal Sire"))
            if "index_lite.json" in url:
                response = httpx.Response(404)
                raise httpx.HTTPStatusError(
                    "404", request=httpx.Request("GET", url), response=response,
                )
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake)
        monkeypatch.setattr("rs_mcp_server.tools.player_progress.http_get", fake)

        result = await get_player_achievement_progress("Noxious Foe", "ghostplayer", "osrs")
        # Achievement info still renders
        assert "**Noxious Foe**" in result
        # Plus privacy-aware message
        assert "No public hiscores" in result
        assert "ghostplayer" in result


class TestNotFound:
    @pytest.mark.anyio
    async def test_achievement_not_found_no_hiscores_call(self, monkeypatch):
        hiscores_called = {"n": 0}

        async def fake(url, params=None, timeout=10.0):
            if "runescape.wiki" in url or "oldschool.runescape.wiki" in url:
                # Both _fetch_page and _search_achievement see no results
                if (params or {}).get("generator") == "search":
                    return {"query": {"pages": []}}
                return {"query": {"pages": [{"missing": True}]}}
            if "index_lite.json" in url:
                hiscores_called["n"] += 1
                raise AssertionError("hiscores should not be called when achievement is not found")
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake)
        monkeypatch.setattr("rs_mcp_server.tools.player_progress.http_get", fake)

        result = await get_player_achievement_progress("zzznotanachievement", "Lynx Titan", "osrs")
        assert "No achievement found" in result
        assert hiscores_called["n"] == 0


class TestValidation:
    @pytest.mark.anyio
    async def test_unknown_game(self):
        result = await get_player_achievement_progress("Noxious Foe", "Lynx Titan", "rs2")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_empty_name(self):
        result = await get_player_achievement_progress("", "Lynx Titan", "osrs")
        assert "required" in result

    @pytest.mark.anyio
    async def test_empty_username(self):
        result = await get_player_achievement_progress("Noxious Foe", "", "osrs")
        assert "required" in result

    @pytest.mark.anyio
    async def test_invalid_username_rejected(self):
        # Short-circuits (before any API call) with a clear message — previously
        # an invalid username reached the hiscores API and 403-crashed.
        result = await get_player_achievement_progress("Peach Conjurer", "<script>", "osrs")
        assert "isn't a valid RuneScape name" in result


class TestFormatProgressRobustness:
    def test_combat_achievement_activity_missing_fields(self):
        # Activity dict missing rank/score (or string-typed) must not crash.
        data = {"activities": [{"name": "Commander Zilyana"}]}
        out = _format_progress("Combat Achievement", "Commander Zilyana", "Tester", data)
        assert "Commander Zilyana" in out

    def test_combat_achievement_string_rank(self):
        data = {"activities": [{"name": "Commander Zilyana", "rank": "5", "score": "50"}]}
        out = _format_progress("Combat Achievement", "Commander Zilyana", "Tester", data)
        assert "50 KCs" in out
