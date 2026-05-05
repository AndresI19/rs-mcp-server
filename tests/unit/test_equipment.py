"""End-to-end tests for the get_equipment_stats MCP tool (issue #44)."""
import pytest

from rs_mcp_server.tools.equipment import get_equipment_stats


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


_OSRS_WHIP_BONUSES = (
    "{{Infobox Bonuses\n"
    "|astab = 0\n"
    "|aslash = +82\n"
    "|acrush = 0\n"
    "|amagic = 0\n"
    "|arange = 0\n"
    "|dstab = 0\n"
    "|dslash = 0\n"
    "|dcrush = 0\n"
    "|dmagic = 0\n"
    "|drange = 0\n"
    "|str = +82\n"
    "|rstr = 0\n"
    "|mdmg = 0\n"
    "|prayer = 0\n"
    "|slot = weapon\n"
    "|speed = 4\n"
    "|attackrange = 1\n"
    "|combatstyle = Whip\n"
    "}}"
)


class TestGetEquipmentStatsOsrs:
    @pytest.mark.anyio
    async def test_returns_stat_block(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Abyssal whip", _OSRS_WHIP_BONUSES)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Abyssal whip", "osrs")
        assert "**Abyssal whip** (OSRS Wiki)" in result
        assert "**Slot:** weapon" in result
        assert "**Attack slash:** +82" in result
        assert "**Strength:** +82" in result
        assert "**Combat style:** Whip" in result

    @pytest.mark.anyio
    async def test_disambiguation_when_titles_dont_match(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Abyssal whip", _OSRS_WHIP_BONUSES)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Abby whip", "osrs")
        assert result.startswith("Did you mean")
        assert "Abyssal whip" in result
        assert "OSRS Wiki" in result

    @pytest.mark.anyio
    async def test_no_combat_stats_when_template_missing(self, monkeypatch):
        page_without_bonuses = _wiki_page("Bones", "Just an article body, no infobox bonuses here.")

        async def fake_http_get(url, params=None, timeout=10.0):
            return page_without_bonuses

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Bones", "osrs")
        assert "**Bones**" in result
        assert "No combat stats found" in result

    @pytest.mark.anyio
    async def test_no_equipment_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("generator") == "search":
                return {"query": {"pages": []}}
            return _missing()

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("zzznotaitemzzz", "osrs")
        assert result.startswith("No equipment found")
        assert "OSRS" in result


class TestGetEquipmentStatsRs3:
    @pytest.mark.anyio
    async def test_returns_rs3_stat_block(self, monkeypatch):
        wikitext = (
            "{{Infobox Bonuses\n"
            "|class = melee\n"
            "|slot = weapon\n"
            "|tier = 70\n"
            "|damage = 672\n"
            "|accuracy = 1486\n"
            "|style = Slash\n"
            "|attack_range = 1\n"
            "|speed = 4\n"
            "}}"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Abyssal whip", wikitext)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Abyssal whip", "rs3")
        assert "**Abyssal whip** (RS3 Wiki)" in result
        assert "**Tier:** 70" in result
        assert "**Damage:** 672" in result
        assert "**Accuracy:** 1486" in result
        assert "**Style:** Slash" in result


class TestGetEquipmentStatsRs3Armour:
    @pytest.mark.anyio
    async def test_armour_fields_render(self, monkeypatch):
        wikitext = (
            "{{Infobox Bonuses\n"
            "|requirements = {{sc|defence|90}}\n"
            "|class = ranged\n"
            "|slot = head\n"
            "|tier = 90\n"
            "|type = power\n"
            "|armour = 435.6\n"
            "|prayer = 2\n"
            "|ranged = 22.5\n"
            "}}"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Sirenic mask", wikitext)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Sirenic mask", "rs3")
        assert "**Sirenic mask** (RS3 Wiki)" in result
        assert "**Armour:** 435.6" in result
        assert "**Prayer:** 2" in result
        assert "**Ranged damage:** 22.5" in result
        assert "**Tier:** 90" in result
        # Weapon-shape fields shouldn't render for armour pieces
        assert "**Damage:**" not in result
        assert "**Accuracy:**" not in result


class TestGetEquipmentStatsValidation:
    @pytest.mark.anyio
    async def test_unknown_game_returns_error(self):
        result = await get_equipment_stats("Abyssal whip", "invalidgame")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_empty_name_returns_error(self):
        result = await get_equipment_stats("", "osrs")
        assert "No item name provided" in result

    @pytest.mark.anyio
    async def test_whitespace_name_returns_error(self):
        result = await get_equipment_stats("   ", "osrs")
        assert "No item name provided" in result
