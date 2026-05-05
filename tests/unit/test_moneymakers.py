"""End-to-end tests for the money-maker MCP tools (issue #43)."""
import pytest

from rs_mcp_server.tools.moneymakers import (
    get_money_makers,
    get_money_maker_method,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_OSRS_MASTER_HTML = """
<h2>Hourly profit table</h2>
<table class="wikitable sortable">
<tr>
  <th>Method</th><th>Hourly profit</th><th>Skills</th>
  <th>Category</th><th>Intensity</th><th>Members</th>
</tr>
<tr>
  <td><a href="/w/Money_making_guide/Method_A">Method A</a></td>
  <td data-sort-value="5000000"><span>5,000,000</span></td>
  <td>99 Attack</td>
  <td>Combat/High</td>
  <td>High</td>
  <td><img alt="Members icon" src="/x.png"/></td>
</tr>
<tr>
  <td><a href="/w/Money_making_guide/Method_B">Method B</a></td>
  <td data-sort-value="2000000"><span>2,000,000</span></td>
  <td>50 Mining</td>
  <td>Gathering</td>
  <td>Low</td>
  <td></td>
</tr>
<tr>
  <td><a href="/w/Money_making_guide/Method_C">Method C</a></td>
  <td data-sort-value="3000000"><span>3,000,000</span></td>
  <td>70 Slayer</td>
  <td>Combat/Med</td>
  <td>Moderate</td>
  <td><img alt="Members icon" src="/x.png"/></td>
</tr>
</table>
"""

_RS3_MASTER_HTML = """
<h2>Hourly profit</h2>
<table class="wikitable sortable">
<tr>
  <th>Method</th><th>Hourly profit</th><th>Skills required</th>
</tr>
<tr>
  <td><a href="/w/Money_making_guide/Method_X">Method X</a></td>
  <td data-sort-value="100000000"><span>100,000,000</span></td>
  <td>99 Attack</td>
</tr>
<tr>
  <td><a href="/w/Money_making_guide/Method_Y">Method Y</a></td>
  <td data-sort-value="50000000"><span>50,000,000</span></td>
  <td>80 Mining</td>
</tr>
</table>
"""

_MMGTABLE_BIRD_HOUSES = (
    "{{Mmgtable\n"
    "|Activity = Bird house trapping\n"
    "|Category = Gathering\n"
    "|Intensity = Low\n"
    "|Members = Yes\n"
    "|Skill = {{mmgreq|Hunter|5}}, {{mmgreq|Crafting|5}}\n"
    "|Item = [[Logs]], [[Hammer]]\n"
    "|Quest = \n"
    "|Input1 = Logs\n"
    "|Input1num = 4\n"
    "|Input2 = Bird seed\n"
    "|Input2num = 4\n"
    "|Output1 = Bird nest\n"
    "|Output1num = 12\n"
    "|Details = Set up bird houses every 50 minutes; collect rewards on each trip.\n"
    "}}"
)

_MMGTABLE_RECURRING = (
    "{{Mmgtable recurring\n"
    "|Activity = Daily ore boxes\n"
    "|Category = Processing\n"
    "|Intensity = Low\n"
    "|Recurrence time = 24:00:00\n"
    "|Skill = {{mmgreq|Mining|60}}\n"
    "|Output1 = Coal ore\n"
    "|Output1num = 100\n"
    "|Details = Empty your ore box once daily.\n"
    "}}"
)


def _master_response(html_text: str) -> dict:
    return {"parse": {"text": html_text}}


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


# ---------------------------------------------------------------------------
# Tool 1 tests
# ---------------------------------------------------------------------------

class TestGetMoneyMakers:
    @pytest.mark.anyio
    async def test_returns_top_n_ranked(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _master_response(_OSRS_MASTER_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_makers(game="osrs", limit=2)
        assert "**Hourly profit money-making methods (OSRS)**" in result
        assert "Method A" in result
        assert "5,000,000" in result
        assert "Method C" in result
        assert "3,000,000" in result
        assert "Method B" not in result

    @pytest.mark.anyio
    async def test_members_only_filter(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _master_response(_OSRS_MASTER_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_makers(game="osrs", members_only=True, limit=10)
        assert "Method A" in result
        assert "Method C" in result
        assert "Method B" not in result

    @pytest.mark.anyio
    async def test_category_filter_combat_osrs(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _master_response(_OSRS_MASTER_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_makers(game="osrs", category="combat", limit=10)
        assert "Method A" in result
        assert "Method C" in result
        assert "Method B" not in result

    @pytest.mark.anyio
    async def test_category_filter_skilling_osrs(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _master_response(_OSRS_MASTER_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_makers(game="osrs", category="skilling", limit=10)
        assert "Method B" in result
        assert "Method A" not in result
        assert "Method C" not in result

    @pytest.mark.anyio
    async def test_category_filter_noop_on_rs3(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _master_response(_RS3_MASTER_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_makers(game="rs3", category="combat", limit=10)
        assert "category filtering not available on RS3" in result
        # Both rows still show up since the filter was ignored
        assert "Method X" in result
        assert "Method Y" in result

    @pytest.mark.anyio
    async def test_rs3_table_has_no_category_column(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _master_response(_RS3_MASTER_HTML)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_makers(game="rs3", limit=10)
        assert "**Hourly profit money-making methods (RS3)**" in result
        # RS3 fixture has no Category column → header should not include it
        first_table_line = next(line for line in result.splitlines() if line.startswith("| Rank"))
        assert "Category" not in first_table_line
        assert "Intensity" not in first_table_line

    @pytest.mark.anyio
    async def test_unknown_game_returns_error(self):
        result = await get_money_makers(game="invalidgame")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_unknown_category_returns_error(self):
        result = await get_money_makers(game="osrs", category="floofing")
        assert "Unknown category" in result


# ---------------------------------------------------------------------------
# Tool 2 tests
# ---------------------------------------------------------------------------

class TestGetMoneyMakerMethod:
    @pytest.mark.anyio
    async def test_returns_method_detail(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Money making guide/Bird house trapping", _MMGTABLE_BIRD_HOUSES)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_maker_method("Bird house trapping", "osrs")
        assert "**Bird house trapping** (OSRS Wiki)" in result
        assert "**Category:** Gathering" in result
        assert "**Intensity:** Low" in result
        assert "**Skills:**" in result
        assert "Level 5 Hunter" in result
        assert "Level 5 Crafting" in result
        assert "**Inputs:**" in result
        assert "4 Logs" in result
        assert "**Outputs:**" in result
        assert "12 Bird nest" in result

    @pytest.mark.anyio
    async def test_recurring_template_variant(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Money making guide/Daily ore boxes", _MMGTABLE_RECURRING)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_maker_method("Daily ore boxes", "osrs")
        assert "**Daily ore boxes** (OSRS Wiki)" in result
        assert "**Recurrence time:** 24:00:00" in result
        assert "recurring activity" in result

    @pytest.mark.anyio
    async def test_disambiguation_when_titles_dont_match(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            return _wiki_page("Money making guide/Bird house trapping", _MMGTABLE_BIRD_HOUSES)

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_maker_method("birdhouses", "osrs")
        assert result.startswith("Did you mean")
        assert "Bird house trapping" in result

    @pytest.mark.anyio
    async def test_no_method_found(self, monkeypatch):
        async def fake_http_get(url, params=None, timeout=10.0):
            if (params or {}).get("generator") == "search":
                return {"query": {"pages": []}}
            return _missing()

        monkeypatch.setattr("rs_mcp_server.tools.moneymakers.http_get", fake_http_get)
        result = await get_money_maker_method("zzznotamethodzzz", "rs3")
        assert "No money-making method found" in result

    @pytest.mark.anyio
    async def test_unknown_game_returns_error(self):
        result = await get_money_maker_method("Bird house trapping", "invalid")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_empty_name_returns_error(self):
        result = await get_money_maker_method("", "osrs")
        assert "No method name provided" in result
