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
        page_without_infobox = _wiki_page("Cabbage", "Just an article body, no infobox monster here.")

        async def fake_http_get(url, params=None, timeout=10.0):
            return page_without_infobox

        monkeypatch.setattr("rs_mcp_server.tools.monsters.http_get", fake_http_get)
        result = await get_monster_info("Cabbage", "osrs")
        assert "**Cabbage**" in result
        assert "No monster info found" in result

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
