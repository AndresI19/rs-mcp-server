"""End-to-end tests for the get_item_recipe MCP tool (issue #40)."""
import pytest

from rs_mcp_server.tools.recipes import get_item_recipe


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


class TestGetItemRecipeRs3:
    @pytest.mark.anyio
    async def test_happy_path(self, monkeypatch):
        wikitext = (
            "{{Infobox Recipe\n"
            "|members = Yes\n"
            "|ticks = 960\n"
            "|skill1 = Fletching\n"
            "|skill1lvl = 110\n"
            "|skill1exp = 160.0\n"
            "|skill1boostable = Yes\n"
            "|achievement1 = Fletch Quest\n"
            "|mat1 = [[Masterwork bow (untillered)]]\n"
            "|output1 = Masterwork bow\n"
            "}}"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Masterwork bow", wikitext)

        monkeypatch.setattr("rs_mcp_server.tools.recipes.http_get", fake_http_get)
        result = await get_item_recipe("Masterwork bow", "rs3")
        assert "**Masterwork bow** (RS3 Wiki)" in result
        assert "Level 110 Fletching" in result
        assert "160.0 xp" in result
        assert "boostable" in result
        assert "Masterwork bow (untillered)" in result
        assert "Fletch Quest" in result
        assert "**Members:** Yes" in result
        assert "**Time:** 960 ticks" in result
        assert "**Output:** Masterwork bow" in result

    @pytest.mark.anyio
    async def test_recipe_not_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return {"query": {"pages": [{"missing": True}]}}

        monkeypatch.setattr("rs_mcp_server.tools.recipes.http_get", fake_http_get)
        result = await get_item_recipe("nosuchitem", "rs3")
        assert result == "Recipe for 'nosuchitem' not found on the RS3 wiki."

    @pytest.mark.anyio
    async def test_no_recipe_template_on_page(self, monkeypatch):
        # Page exists but has no recipe template (e.g., a quest article)
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Cook's Assistant", "{{Infobox Quest|members=No}}\nSome quest article body.")

        monkeypatch.setattr("rs_mcp_server.tools.recipes.http_get", fake_http_get)
        result = await get_item_recipe("Cook's Assistant", "rs3")
        assert "**Cook's Assistant** (RS3 Wiki)" in result
        assert "No recipe template found on this page" in result


class TestGetItemRecipeOsrs:
    @pytest.mark.anyio
    async def test_happy_path(self, monkeypatch):
        wikitext = (
            "{{Recipe\n"
            "|skill1 = Smithing\n"
            "|skill1lvl = 68\n"
            "|skill1exp = 250\n"
            "|members = No\n"
            "|ticks = 5\n"
            "|tools = Hammer\n"
            "|facilities = Anvil\n"
            "|mat1 = [[Mithril bar]]\n"
            "|mat1quantity = 5\n"
            "|output1 = Mithril platebody\n"
            "}}"
        )

        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Mithril platebody", wikitext)

        monkeypatch.setattr("rs_mcp_server.tools.recipes.http_get", fake_http_get)
        result = await get_item_recipe("Mithril platebody", "osrs")
        assert "**Mithril platebody** (OSRS Wiki)" in result
        assert "Level 68 Smithing" in result
        assert "250 xp" in result
        assert "5 Mithril bar" in result
        assert "**Tools:** Hammer" in result
        assert "**Facilities:** Anvil" in result
        assert "**Members:** No" in result
        assert "**Output:** Mithril platebody" in result
