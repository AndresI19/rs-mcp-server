"""End-to-end tests for the get_monster_info MCP tool (issue #49)."""

import pytest

from rs_mcp_server.tools.monsters import get_monster_info


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


_OSRS_ABYSSAL_DEMON = (
    "{{Infobox Monster\n"
    "|members = Yes\n"
    "|combat = 124\n"
    "|examine = A denizen of the Abyss!\n"
    "|attributes = demon\n"
    "|max hit = 8\n"
    "|aggressive = No\n"
    "|poisonous = No\n"
    "|attack style = [[Stab]]\n"
    "|attack speed = 4\n"
    "|slaylvl = 85\n"
    "|slayxp = 150\n"
    "|cat = Abyssal Demons\n"
    "|assignedby = vannaka,chaeldar,konar,nieve,duradel,krystilia\n"
    "|hitpoints = 150\n"
    "}}"
)


_RS3_TORMENTED_DEMON = (
    "{{Infobox Monster\n"
    "|members = Yes\n"
    "|examine = Lucien must be incredibly powerful if he can bind such demons to his will.\n"
    "|level = 119\n"
    "|lifepoints = 20,000\n"
    "|experience = 1000\n"
    "|aggressive1 = Yes\n"
    "|poisonous = No\n"
    "|slaylvl = 1\n"
    "|slayxp = 1136\n"
    "|slayercat = Tormented demons, Demons\n"
    "|assigned_by = kuradal,morvran,laniakea\n"
    "|style = melee, range, magic\n"
    "|primarystyle = magic\n"
    "|speed = 7\n"
    "|weakness1 = Fire\n"
    "|weakness2 = Bolts\n"
    "|susceptibility = Demon slayer\n"
    "|armour = 1694\n"
    "|defence = 70\n"
    "}}"
)


class TestGetMonsterInfoOsrs:
    @pytest.mark.anyio
    async def test_returns_stat_block(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Abyssal demon", _OSRS_ABYSSAL_DEMON)

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("Abyssal demon", "osrs")
        assert "**Abyssal demon** (OSRS Wiki)" in result
        assert "**Combat level:** 124" in result
        assert "**Hitpoints:** 150" in result
        assert "**Slayer level:** 85" in result
        assert "**Slayer XP:** 150" in result
        assert "**Attack style:** Stab" in result
        assert "**Members:** Yes" in result
        assert "**Examine:** A denizen of the Abyss!" in result

    @pytest.mark.anyio
    async def test_disambiguation_when_titles_dont_match(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Abyssal demon", _OSRS_ABYSSAL_DEMON)

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("abby demon", "osrs")
        assert result.startswith("Did you mean")
        assert "Abyssal demon" in result
        assert "OSRS Wiki" in result

    @pytest.mark.anyio
    async def test_no_info_when_template_missing(self, monkeypatch):
        # Page exists but has no monster infobox. Search filter rejects it →
        # tool returns the cleaner "No monster found" message (#76).
        page_without_infobox = _wiki_page(
            "Cabbage", "Just an article body, no infobox monster here."
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            return page_without_infobox

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("Cabbage", "osrs")
        assert "No monster found for 'Cabbage'" in result

    @pytest.mark.anyio
    async def test_no_monster_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("generator") == "search":
                return {"query": {"pages": []}}
            return _missing()

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("zzznotamonsterzzz", "osrs")
        assert result.startswith("No monster found")
        assert "OSRS" in result


class TestGetMonsterInfoRs3:
    @pytest.mark.anyio
    async def test_returns_rs3_stat_block(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Tormented demon", _RS3_TORMENTED_DEMON)

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("Tormented demon", "rs3")
        assert "**Tormented demon** (RS3 Wiki)" in result
        assert "**Combat level:** 119" in result
        assert "**Life points:** 20,000" in result
        assert "**Combat XP:** 1000" in result
        assert "**Slayer level:** 1" in result
        assert "**Slayer XP:** 1136" in result
        assert "**Weakness:** Fire" in result
        assert "**Aggressive:** Yes" in result
        assert "**Susceptibility:** Demon slayer" in result


class TestGetMonsterInfoValidation:
    @pytest.mark.anyio
    async def test_unknown_game_returns_error(self):
        result = await get_monster_info("Abyssal demon", "invalidgame")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_empty_name_returns_error(self):
        result = await get_monster_info("", "osrs")
        assert "No monster name provided" in result

    @pytest.mark.anyio
    async def test_whitespace_name_returns_error(self):
        result = await get_monster_info("   ", "osrs")
        assert "No monster name provided" in result


class TestSearchTypeFilter:
    """Issue #76 — search must skip pages whose content doesn't carry an Infobox Monster."""

    @pytest.mark.anyio
    async def test_search_skips_wrong_type_candidates(self, monkeypatch):
        def page_revision(title, content):
            return {"title": title, "revisions": [{"slots": {"main": {"content": content}}}]}

        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("generator") != "search":
                return {"query": {"pages": [{"missing": True}]}}
            return {
                "query": {
                    "pages": [
                        page_revision("Random NPC", "{{Infobox NPC|name=Random}}"),
                        page_revision("Quest about demons", "{{Infobox Quest|difficulty=Hard}}"),
                        page_revision(
                            "Demonic creature",
                            "{{Infobox Monster\n|combat = 100\n|hitpoints = 1000\n|members = Yes\n}}",
                        ),
                    ]
                }
            }

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("Demonic creature", "osrs")
        assert "**Demonic creature**" in result
        assert "Combat level" in result
        # Wrong-type candidates must not appear
        assert "Random NPC" not in result
        assert "Quest" not in result


class TestDisambigSuffixFallback:
    """Issue #75 — bare name returns wrong-type page; retry with (monster) then (NPC) suffix."""

    @pytest.mark.anyio
    async def test_resolves_via_monster_suffix(self, monkeypatch):
        # Bare "Tarn Razorlor" → NPC profile (no Infobox Monster).
        # "Tarn Razorlor (monster)" → the right monster page.
        npc_wikitext = "{{Infobox NPC|name = Tarn Razorlor|race = Human}}"
        monster_wikitext = (
            "{{Infobox Monster\n"
            "|name = Tarn Razorlor\n"
            "|combat = 69\n"
            "|hitpoints = 60\n"
            "|members = Yes\n"
            "}}"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            title = (params or {}).get("titles", "")
            if title == "Tarn Razorlor":
                return _wiki_page("Tarn Razorlor", npc_wikitext)
            if title == "Tarn Razorlor (monster)":
                return _wiki_page("Tarn Razorlor (monster)", monster_wikitext)
            raise AssertionError(f"unexpected titles param: {title}")

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("Tarn Razorlor", "osrs")
        assert "**Tarn Razorlor (monster)**" in result
        assert "Combat level" in result
        assert "Did you mean" not in result

    @pytest.mark.anyio
    async def test_falls_through_to_npc_suffix_when_monster_misses(self, monkeypatch):
        # Bare "Some Guy" → wrong type. (monster) → also wrong type. (NPC) → right type.
        # Tests the suffix-loop ordering.
        wrong_wikitext = "{{Infobox Character|name = Some Guy}}"
        monster_wikitext = "{{Infobox Monster\n|name = Some Guy\n|combat = 5\n|hitpoints = 10\n}}"

        async def fake_http_get(url, params=None, timeout=10.0):
            title = (params or {}).get("titles", "")
            if title == "Some Guy":
                return _wiki_page("Some Guy", wrong_wikitext)
            if title == "Some Guy (monster)":
                return _wiki_page("Some Guy (monster)", wrong_wikitext)
            if title == "Some Guy (NPC)":
                return _wiki_page("Some Guy (NPC)", monster_wikitext)
            raise AssertionError(f"unexpected titles param: {title}")

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("Some Guy", "osrs")
        assert "**Some Guy (NPC)**" in result
        assert "Combat level" in result
