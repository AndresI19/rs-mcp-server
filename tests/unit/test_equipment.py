"""End-to-end tests for the get_equipment_stats MCP tool (issues #44, #77)."""

import httpx
import pytest

from rs_mcp_server import cache as _cache_mod
from rs_mcp_server.tools.equipment import get_equipment_stats


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


def _missing() -> dict:
    return {"query": {"pages": [{"missing": True}]}}


def _parse_html(text: str) -> dict:
    return {"parse": {"text": text}}


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
        # Page exists but has no Infobox Bonuses. Search filter rejects it →
        # tool returns the cleaner "No equipment found" message (#76).
        page_without_bonuses = _wiki_page("Bones", "Just an article body, no infobox bonuses here.")

        async def fake_http_get(url, params=None, timeout=10.0):
            return page_without_bonuses

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Bones", "osrs")
        assert "No equipment found for 'Bones'" in result

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


class TestGetEquipmentStatsNamedSections:
    """Issue #77 — surface Set bonus / Passive / Special properties prose alongside infobox."""

    _BONUSES = "{{Infobox Bonuses\n|class = melee\n|slot = head\n|tier = 92\n|armour = 700\n}}"

    @pytest.mark.anyio
    async def test_set_bonus_section_appended_when_present(self, monkeypatch):
        parse_html = (
            '<div class="mw-parser-output">'
            "<p>Lead paragraph about the helm.</p>"
            '<h2 id="Set_bonus">Set bonus</h2>'
            "<p>Wearing the full set grants 50% incoming damage delayed as bleed.</p>"
            "</div>"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("action") == "parse":
                return _parse_html(parse_html)
            return _wiki_page("Trimmed masterwork melee helm", self._BONUSES)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Trimmed masterwork melee helm", "rs3")
        assert "**Tier:** 92" in result
        assert "## Set bonus" in result
        assert "50% incoming damage delayed as bleed" in result

    @pytest.mark.anyio
    async def test_passive_alias_renders_as_canonical_label(self, monkeypatch):
        # Wiki uses "Passive effect" as the heading; output should use canonical "Passive".
        parse_html = (
            "<div>"
            '<h2 id="Passive_effect">Passive effect</h2>'
            "<p>Herald of Chaos: adrenaline regen, Berserk extension, +20% adren cap.</p>"
            "</div>"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("action") == "parse":
                return _parse_html(parse_html)
            return _wiki_page("Vestments of Havoc helm", self._BONUSES)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Vestments of Havoc helm", "rs3")
        assert "## Passive" in result
        # Canonical label, NOT the heading variant
        assert "## Passive effect" not in result
        assert "Herald of Chaos" in result

    @pytest.mark.anyio
    async def test_missing_sections_render_nothing(self, monkeypatch):
        # Page has prose but no Set bonus / Passive / Special properties headings.
        parse_html = '<div><h2 id="History">History</h2><p>Some lore text.</p></div>'

        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("action") == "parse":
                return _parse_html(parse_html)
            return _wiki_page("Abyssal whip", self._BONUSES)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Abyssal whip", "rs3")
        assert "**Tier:** 92" in result
        assert "## Set bonus" not in result
        assert "## Passive" not in result
        assert "## Special properties" not in result

    @pytest.mark.anyio
    async def test_parse_failure_swallowed_infobox_still_returns(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("action") == "parse":
                raise httpx.ConnectError("transient parse-api outage")
            return _wiki_page("Trimmed masterwork melee helm", self._BONUSES)

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Trimmed masterwork melee helm", "rs3")
        # Infobox stats still render; no enrichment, no exception.
        assert "**Tier:** 92" in result
        assert "## Set bonus" not in result


class TestSearchTypeFilter:
    """Issue #76 — search must skip pages whose content doesn't carry an Infobox Bonuses."""

    @pytest.mark.anyio
    async def test_search_skips_wrong_type_candidates(self, monkeypatch):
        def page_revision(title, content):
            return {"title": title, "revisions": [{"slots": {"main": {"content": content}}}]}

        async def fake_http_get(url, params=None, timeout=10.0):
            # Direct fetch returns missing; search returns 3 candidates
            if (params or {}).get("generator") != "search":
                return {"query": {"pages": [{"missing": True}]}}
            if (params or {}).get("action") == "parse":
                # _fetch_named_sections may be called by the success path — return empty
                return {"parse": {"text": "<div></div>"}}
            return {
                "query": {
                    "pages": [
                        page_revision(
                            "Damage bonus", "{{Infobox Skill|name=Damage bonus}}"
                        ),  # game-mechanic page, not equipment
                        page_revision("Life points", "{{Infobox Skill|name=Life points}}"),
                        page_revision(
                            "Some helm",
                            "{{Infobox Bonuses\n|slot = head\n|tier = 92\n|armour = 457\n|prayer = 2\n}}",
                        ),
                    ]
                }
            }

        monkeypatch.setattr("rs_mcp_server.tools.equipment.http_get", fake_http_get)
        result = await get_equipment_stats("Some helm", "rs3")
        assert "**Some helm**" in result
        assert "**Tier:** 92" in result
        # Wrong-type candidates must not appear
        assert "Damage bonus" not in result
        assert "Life points" not in result


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
