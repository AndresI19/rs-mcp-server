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
        # Page exists but has no achievement infobox. Search filter rejects it →
        # tool returns the cleaner "No achievement found" message (#76).
        page_without_infobox = _wiki_page(
            "Cabbage", "Just an article body, no achievement infobox here."
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            return page_without_infobox

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Cabbage", "osrs")
        assert "No achievement found for 'Cabbage'" in result

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


class TestSearchTypeFilter:
    """Issue #76 — search must skip pages whose content doesn't carry an achievement template."""

    @pytest.mark.anyio
    async def test_search_skips_wrong_type_candidates(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            # Direct fetch by exact title → missing, forces fall-through to search
            if (params or {}).get("generator") != "search":
                return {"query": {"pages": [{"missing": True}]}}
            # Search returns 3 candidates: minigame + category + achievement
            return {
                "query": {
                    "pages": [
                        {
                            "title": "Pest Control",
                            "revisions": [
                                {
                                    "slots": {
                                        "main": {
                                            "content": "{{Infobox Minigame|name=Pest Control}}"
                                        }
                                    }
                                }
                            ],
                        },
                        {
                            "title": "Some category",
                            "revisions": [
                                {"slots": {"main": {"content": "[[Category:Achievements]]"}}}
                            ],
                        },
                        {
                            "title": "Are you winning yet",
                            "revisions": [
                                {
                                    "slots": {
                                        "main": {
                                            "content": "{{Infobox Combat Achievement|tier=Easy|description=Win.|monster=Test}}"
                                        }
                                    }
                                }
                            ],
                        },
                    ]
                }
            }

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Are you winning yet", "osrs")
        # Resolved to the achievement page (passed type filter), not Pest Control or category
        assert "**Are you winning yet**" in result
        assert "Pest Control" not in result
        assert "category" not in result.lower() or "category:" not in result.lower()


class TestRomanVariantEnumeration:
    """Issue #78 — when bare name 404s but '<name> I/II/III' achievements exist, enumerate them."""

    @pytest.mark.anyio
    async def test_enumerates_variants_when_bare_404s(self, monkeypatch):
        # "Are You Winning, Zam?" bare page is missing; I/II/III all exist with achievement infoboxes.
        def page(title, content):
            return {"title": title, "revisions": [{"slots": {"main": {"content": content}}}]}

        ach_template = "{{Infobox Achievement\n|description = Defeat Zamorak.\n|score = 50\n}}"

        async def fake_http_get(url, params=None, timeout=10.0):
            titles = (params or {}).get("titles", "")
            # Bare-name direct fetch
            if titles == "Are You Winning, Zam?":
                return {"query": {"pages": [{"missing": True}]}}
            # Disambig-suffix retry — also missing
            if titles == "Are You Winning, Zam? (achievement)":
                return {"query": {"pages": [{"missing": True}]}}
            # Batch variant query (pipe-separated)
            if "|" in titles:
                return {
                    "query": {
                        "pages": [
                            page("Are You Winning, Zam? I", ach_template),
                            page("Are You Winning, Zam? II", ach_template),
                            page("Are You Winning, Zam? III", ach_template),
                            {"title": "Are You Winning, Zam? IV", "missing": True},
                            {"title": "Are You Winning, Zam? V", "missing": True},
                        ]
                    }
                }
            raise AssertionError(f"unexpected titles param: {titles!r}")

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Are You Winning, Zam?", "rs3")
        assert "Multiple tiered variants" in result
        assert "Are You Winning, Zam? I" in result
        assert "Are You Winning, Zam? II" in result
        assert "Are You Winning, Zam? III" in result
        # IV/V were missing, must not appear
        assert "Are You Winning, Zam? IV" not in result
        assert "Are You Winning, Zam? V" not in result


class TestDisambigSuffixFallback:
    """Issue #75 — bare name returns wrong-type page; retry with (achievement) suffix."""

    @pytest.mark.anyio
    async def test_flow_state_resolves_via_achievement_suffix(self, monkeypatch):
        # Bare "Flow State" returns a relic page (no Infobox Achievement).
        # "Flow State (achievement)" returns the right achievement page.
        relic_wikitext = "{{Infobox Relic\n|name = Flow State\n|tier = Lesser\n}}"
        achievement_wikitext = (
            "{{Infobox Achievement\n"
            "|name = Flow State\n"
            "|description = Open the Necromancy spellbook.\n"
            "|score = 10\n"
            "|maincategory = Skills\n"
            "|subcategory = Necromancy\n"
            "|members = Yes\n"
            "|release = 7 August 2023\n"
            "}}"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            title = (params or {}).get("titles", "")
            if title == "Flow State":
                return _wiki_page("Flow State", relic_wikitext)
            if title == "Flow State (achievement)":
                return _wiki_page("Flow State (achievement)", achievement_wikitext)
            raise AssertionError(f"unexpected titles param: {title}")

        monkeypatch.setattr("rs_mcp_server.tools.achievements.http_get", fake_http_get)
        result = await get_achievement("Flow State", "rs3")
        # Resolved via suffix retry → returns the achievement page, not the relic
        assert "**Flow State (achievement)**" in result
        assert "Achievement" in result
        assert "Open the Necromancy spellbook" in result
        # Should NOT show disambiguation message — suffix retry is treated as success
        assert "Did you mean" not in result


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
