"""End-to-end tests for the get_achievement MCP tool (issue #54)."""
import pytest

from rs_mcp_server.tools.achievements import get_achievement


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


def _missing() -> dict:
    return {"query": {"pages": [{"missing": True}]}}


_OSRS_NOXIOUS_FOE = (
    "{{Infobox Combat Achievement\n"
    "|name = Noxious Foe\n"
    "|release = [[21 July]] [[2021]]\n"
    "|update = Combat Achievements\n"
    "|members = Yes\n"
    "|description = Kill an Aberrant Spectre.\n"
    "|tier = Easy\n"
    "|monster = Aberrant Spectre\n"
    "|type = Kill Count\n"
    "|id = 0\n"
    "|leagueRegion = Morytania\n"
    "}}"
)


_OSRS_FALADOR_DIARY = (
    "{{Infobox Achievement Diary\n"
    "|name = Falador Diary\n"
    "|release = [[5 March]] [[2015]]\n"
    "|update = Achievement Diaries\n"
    "|areas = [[Falador]], [[Rimmington]], [[Taverley]]\n"
    "|members = Yes\n"
    "|reward = [[Falador shield|Shield]]\n"
    "|taskmasters = [[Sir Rebral]]\n"
    "|leagueRegion = Asgarnia\n"
    "}}"
)


_RS3_ESSENCE_OF_MAGIC = (
    "{{Infobox Achievement\n"
    "|id = 447\n"
    "|name = The Essence of Magic\n"
    "|description = Have Wizard Cromperty teleport you to the essence mine.\n"
    "|release = [[10 October]] [[2009]]\n"
    "|update = Ardougne Achievement Diary\n"
    "|members = Yes\n"
    "|score = 5\n"
    "|maincategory = Area Tasks\n"
    "|subcategory = Easy Ardougne\n"
    "|requirements = \n"
    "* None\n"
    "}}"
)


class TestGetAchievementOsrsCa:
    @pytest.mark.anyio
    async def test_returns_combat_achievement_block(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Noxious Foe", _OSRS_NOXIOUS_FOE)

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Noxious Foe", "osrs")
        assert "**Noxious Foe** — Combat Achievement (OSRS Wiki)" in result
        assert "**Description:** Kill an Aberrant Spectre." in result
        assert "**Tier:** Easy" in result
        assert "**Type:** Kill Count" in result
        assert "**Monster:** Aberrant Spectre" in result
        assert "**Members:** Yes" in result
        assert "**League region:** Morytania" in result

    @pytest.mark.anyio
    async def test_disambiguation_when_titles_dont_match(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Noxious Foe", _OSRS_NOXIOUS_FOE)

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("nox foe", "osrs")
        assert result.startswith("Did you mean")
        assert "Noxious Foe" in result
        assert "OSRS Wiki" in result


class TestGetAchievementOsrsDiary:
    @pytest.mark.anyio
    async def test_returns_diary_summary_block(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Falador Diary", _OSRS_FALADOR_DIARY)

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Falador Diary", "osrs")
        assert "**Falador Diary** — Achievement Diary (OSRS Wiki)" in result
        assert "**Areas:** Falador, Rimmington, Taverley" in result
        assert "**Members:** Yes" in result
        assert "**Reward:** Shield" in result
        assert "**Taskmasters:** Sir Rebral" in result
        assert "**League region:** Asgarnia" in result


class TestGetAchievementRs3:
    @pytest.mark.anyio
    async def test_returns_rs3_achievement_block(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("The Essence of Magic", _RS3_ESSENCE_OF_MAGIC)

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("The Essence of Magic", "rs3")
        assert "**The Essence of Magic** — Achievement (RS3 Wiki)" in result
        assert "**Description:** Have Wizard Cromperty teleport you to the essence mine." in result
        assert "**Score:** 5" in result
        assert "**Main category:** Area Tasks" in result
        assert "**Subcategory:** Easy Ardougne" in result
        assert "**Members:** Yes" in result
        assert "**Requirements:**" in result
        assert "None" in result


class TestGetAchievementFallback:
    @pytest.mark.anyio
    async def test_no_info_when_no_achievement_template(self, monkeypatch):
        page_without_infobox = _wiki_page("Cabbage", "Just an article body, no achievement infobox here.")

        async def fake_http_get(url, params=None, timeout=10.0):
            return page_without_infobox

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Cabbage", "osrs")
        assert "**Cabbage**" in result
        assert "No achievement info found" in result

    @pytest.mark.anyio
    async def test_no_achievement_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("generator") == "search":
                return {"query": {"pages": []}}
            return _missing()

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("zzznotaachievementzzz", "osrs")
        assert result.startswith("No achievement found")
        assert "OSRS" in result


class TestGetAchievementDispatchPriority:
    @pytest.mark.anyio
    async def test_combat_achievement_wins_over_achievement(self, monkeypatch):
        """When a page contains both Infobox Combat Achievement and Infobox Achievement,
        the more specific Combat Achievement template wins. This guards the dispatch
        order — Infobox Achievement is a substring of the others' regex unless we
        match the longer names first."""
        mixed = _OSRS_NOXIOUS_FOE + "\n" + _RS3_ESSENCE_OF_MAGIC

        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Noxious Foe", mixed)

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Noxious Foe", "osrs")
        assert "Combat Achievement" in result
        assert "**Tier:** Easy" in result


class TestGetAchievementValidation:
    @pytest.mark.anyio
    async def test_unknown_game_returns_error(self):
        result = await get_achievement("Noxious Foe", "invalidgame")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_empty_name_returns_error(self):
        result = await get_achievement("", "osrs")
        assert "No achievement name provided" in result

    @pytest.mark.anyio
    async def test_whitespace_name_returns_error(self):
        result = await get_achievement("   ", "osrs")
        assert "No achievement name provided" in result
