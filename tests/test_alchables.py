"""End-to-end tests for the get_best_alchables MCP tool (issue #42)."""
import pytest

from rs_mcp_server.tools.alchables import get_best_alchables


# ---------------------------------------------------------------------------
# OSRS fixtures
# ---------------------------------------------------------------------------
#
# Categorization rules under the current formula:
#   Universal filter: 0 < buy_limit <= 100
#   Easy:  daily_volume > 13,000
#   Slow:  daily_volume <  8,000
#   Mid:   8,000 <= daily_volume <= 13,000  (dropped, not surfaced)
#   Mirage marker on Slow items with ROI > 20%
#
# nature rune price = 200 in fixture (id 561 high)
#
# Easy = volume > 13,000 AND buy_limit > 100. Slow = 5,000 < volume < 8,000 AND ROI <= 20.
#
# Item              limit  hourly_v  daily_v   buy    alch    profit  ROI%   bucket / notes
# ----              -----  --------  --------  -----  ------  ------  -----  -------------------------------
# Easy A            200      833     19,992    2000   2800     +600   30.0   easy (limit > 100)
# Easy B            150      750     18,000    1500   2100     +400   26.7   easy
# Easy C            120      600     14,400    1500   2050     +350   23.3   easy (limit just over 100)
# Slow plain         50      290      6,960    1500   1900     +200   13.3   slow (vol in window, ROI < 20)
# Slow mid-roi       70      275      6,600    2000   2560     +360   18.0   slow
# Slow mirage         5      300      7,200   12000  20200    +8000   66.7   excluded (mirage)
# Slow too thin      50       50      1,200    1500   1900     +200   13.3   filtered (vol below 5k)
# Capped             70     2000     48,000    3000   3700     +500   16.7   filtered (vol high but limit ≤ 100)
# Mid (dropped)      50      417     10,008    1000   1500     +300   30.0   mid-bucket (filtered)
# Bulk staple     18000     1000     24,000    8000   9700    +1500   18.8   easy (limit > 100)
# Untradeable         0     1000     24,000    4000   4600     +400   10.0   filtered (limit = 0)
# Loss              200      833     19,992     600    700     -100         filtered (negative profit)

_OSRS_MAPPING = [
    {"id": 561, "name": "Nature rune",    "highalch": 108,  "members": False, "limit": 25000},
    {"id": 1,   "name": "Easy A",         "highalch": 2800, "members": True,  "limit": 200},
    {"id": 2,   "name": "Easy B",         "highalch": 2100, "members": True,  "limit": 150},
    {"id": 3,   "name": "Easy C",         "highalch": 2050, "members": True,  "limit": 120},
    {"id": 4,   "name": "Slow plain",     "highalch": 1900, "members": True,  "limit": 50},
    {"id": 5,   "name": "Slow mirage",    "highalch": 20200,"members": True,  "limit": 5},
    {"id": 6,   "name": "Mid item",       "highalch": 1500, "members": True,  "limit": 50},
    {"id": 7,   "name": "Bulk staple",    "highalch": 9700, "members": True,  "limit": 18000},
    {"id": 8,   "name": "Untradeable",    "highalch": 4600, "members": True,  "limit": 0},
    {"id": 9,   "name": "Loss",           "highalch": 700,  "members": False, "limit": 200},
    {"id": 10,  "name": "Slow mid-roi",   "highalch": 2560, "members": True,  "limit": 70},
    {"id": 11,  "name": "Slow too thin",  "highalch": 1900, "members": True,  "limit": 50},
    {"id": 12,  "name": "Capped",         "highalch": 3700, "members": True,  "limit": 70},
]

_OSRS_LATEST = {
    "data": {
        "561": {"high": 200,   "low": 195},
        "1":   {"high": 2000,  "low": 1990},
        "2":   {"high": 1500,  "low": 1490},
        "3":   {"high": 1500,  "low": 1490},
        "4":   {"high": 1500,  "low": 1490},
        "5":   {"high": 12000, "low": 11900},
        "6":   {"high": 1000,  "low": 990},
        "7":   {"high": 8000,  "low": 7990},
        "8":   {"high": 4000,  "low": 3990},
        "9":   {"high": 600,   "low": 590},
        "10":  {"high": 2000,  "low": 1990},
        "11":  {"high": 1500,  "low": 1490},
        "12":  {"high": 3000,  "low": 2990},
    }
}

_OSRS_1H = {
    "data": {
        "1":  {"highPriceVolume": 833,  "lowPriceVolume": 0},
        "2":  {"highPriceVolume": 750,  "lowPriceVolume": 0},
        "3":  {"highPriceVolume": 600,  "lowPriceVolume": 0},
        "4":  {"highPriceVolume": 290,  "lowPriceVolume": 0},
        "5":  {"highPriceVolume": 300,  "lowPriceVolume": 0},
        "6":  {"highPriceVolume": 417,  "lowPriceVolume": 0},
        "7":  {"highPriceVolume": 1000, "lowPriceVolume": 0},
        "8":  {"highPriceVolume": 1000, "lowPriceVolume": 0},
        "9":  {"highPriceVolume": 833,  "lowPriceVolume": 0},
        "10": {"highPriceVolume": 275,  "lowPriceVolume": 0},
        "11": {"highPriceVolume": 50,   "lowPriceVolume": 0},
        "12": {"highPriceVolume": 2000, "lowPriceVolume": 0},
    }
}


def _osrs_fake_factory(mapping=None, latest=None, hourly=None):
    mapping = _OSRS_MAPPING if mapping is None else mapping
    latest = _OSRS_LATEST if latest is None else latest
    hourly = _OSRS_1H if hourly is None else hourly

    async def fake_http_get(url, params=None, timeout=10.0):
        if "mapping" in url:
            return mapping
        if url.endswith("/1h"):
            return hourly
        if "latest" in url:
            return latest
        raise AssertionError(f"unexpected URL: {url}")

    return fake_http_get


def _patch_osrs(monkeypatch, fake):
    monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", fake)
    monkeypatch.setattr("rs_mcp_server.tools.prices.http_get", fake)


class TestGetBestAlchablesOsrs:
    @pytest.mark.anyio
    async def test_mixed_table_sort_and_filter(self, monkeypatch):
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        # Easy pool by profit:
        #   Bulk staple 1500, Easy A 600, Easy B 400, Easy C 350
        # Top 3 easy: Bulk staple, Easy A, Easy B
        # Slow pool by profit (5k < vol < 8k, limit ≤ 100, ROI ≤ 20):
        #   Slow mid-roi 360, Slow plain 200  (Slow mirage excluded — ROI 66.7%)
        # Top 2 slow: Slow mid-roi, Slow plain
        # Merged + sorted by profit:
        # 1. Bulk staple (1500)
        # 2. Easy A (600)
        # 3. Easy B (400)
        # 4. Slow mid-roi (360)
        # 5. Slow plain (200)
        bs = result.find("Bulk staple")
        ea = result.find("Easy A")
        eb = result.find("Easy B")
        smr = result.find("Slow mid-roi")
        sp = result.find("Slow plain")
        for pos in (bs, ea, eb, smr, sp):
            assert pos != -1
        assert bs < ea < eb < smr < sp
        # Mirages and ineligibles must not appear.
        assert "Slow mirage" not in result       # ROI > 20% → excluded
        assert "Slow too thin" not in result     # daily volume 1,200 → below 5k floor
        assert "Mid item" not in result          # mid-bucket volume
        assert "Easy C" not in result            # bumped out of top 3 by Bulk staple
        assert "Untradeable" not in result       # buy_limit=0
        assert "Loss" not in result              # negative profit

    @pytest.mark.anyio
    async def test_mirage_excluded_no_warning_marker(self, monkeypatch):
        # The ⚠️ marker no longer appears anywhere — mirages are silently dropped.
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        assert "⚠️" not in result
        assert "Slow mirage" not in result

    @pytest.mark.anyio
    async def test_slow_volume_floor_excludes_thin_items(self, monkeypatch):
        # Slow too thin (daily volume 1,200) is below the 5k floor → excluded
        # despite passing all other slow criteria (limit 50, ROI 13.3%).
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        assert "Slow too thin" not in result

    @pytest.mark.anyio
    async def test_easy_requires_high_buy_limit(self, monkeypatch):
        # "Capped" has volume 48,000 (very high) but limit 70 (≤ 100). Under
        # the new rule it must NOT appear in Easy — the per-window cap means
        # you can't actually flood-buy.
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        assert "Capped" not in result

    @pytest.mark.anyio
    async def test_category_tags(self, monkeypatch):
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        assert "🟢 Easy" in result
        assert "🟡 Slow" in result

    @pytest.mark.anyio
    async def test_high_buy_limit_allowed_in_easy_only(self, monkeypatch):
        # Bulk staple has buy_limit=18000 (well above 100) but high volume.
        # It MUST appear in the result tagged 🟢 Easy — high buy limits don't
        # disqualify items from Easy. They only disqualify Slow.
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        bs_line = next(line for line in result.splitlines() if "Bulk staple" in line)
        assert "🟢 Easy" in bs_line
        assert "🟡 Slow" not in bs_line

    @pytest.mark.anyio
    async def test_mid_bucket_volume_dropped(self, monkeypatch):
        # daily_volume 10,008 falls in the [8k, 13k] mid-bucket → dropped.
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        assert "Mid item" not in result

    @pytest.mark.anyio
    async def test_untradeable_items_filtered(self, monkeypatch):
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs")
        assert "Untradeable" not in result

    @pytest.mark.anyio
    async def test_members_only_excludes_f2p(self, monkeypatch):
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs", members_only=True)
        assert "members-only" in result
        # "Loss" is F2P but already filtered (negative profit). Easy A/B/C are members → still appear.
        assert "Easy A" in result

    @pytest.mark.anyio
    async def test_passive_on_osrs_falls_back_to_manual(self, monkeypatch):
        _patch_osrs(monkeypatch, _osrs_fake_factory())
        result = await get_best_alchables(game="osrs", mode="passive")
        assert "no Alchemiser-style passive alching" in result
        # Ranking still produces real items (top non-mirage entry from the merged pool).
        assert "Bulk staple" in result

    @pytest.mark.anyio
    async def test_no_qualifying_items(self, monkeypatch):
        # Move every item's volume into the mid-bucket so neither Easy nor Slow qualifies.
        ids = [str(item["id"]) for item in _OSRS_MAPPING if item["id"] != 561]
        mid_volumes = {
            "data": {i: {"highPriceVolume": 417, "lowPriceVolume": 0} for i in ids}
        }
        fake = _osrs_fake_factory(hourly=mid_volumes)
        _patch_osrs(monkeypatch, fake)
        result = await get_best_alchables(game="osrs")
        assert "No items qualify" in result

    @pytest.mark.anyio
    async def test_missing_nature_rune_price(self, monkeypatch):
        fake = _osrs_fake_factory(latest={"data": {"1": {"high": 100, "low": 99}}})
        _patch_osrs(monkeypatch, fake)
        result = await get_best_alchables(game="osrs")
        assert "Nature rune" in result
        assert "Could not determine" in result

    @pytest.mark.anyio
    async def test_unknown_game_returns_error(self):
        result = await get_best_alchables(game="floofcraft")
        assert "Unknown game" in result

    @pytest.mark.anyio
    async def test_unknown_mode_returns_error(self):
        result = await get_best_alchables(game="osrs", mode="floofmode")
        assert "Unknown mode" in result


# ---------------------------------------------------------------------------
# RS3 fixtures
# ---------------------------------------------------------------------------
#
# Slow window is 5,000 < volume < 8,000.
#
# Item             limit  volume   GE     alch   profit  ROI    MDP         bucket / notes
# ----             -----  -------  -----  ----   ------  -----  ----------  --------------------
# Easy A             100   20,000   2000   2400   +400    20.0    8,000,000  easy
# Easy B              80   18,000   2000   2300   +300    15.0    6,000,000  easy
# Easy C             100   14,000   2000   2350   +350    17.5    7,000,000  easy (just over 13k)
# Slow plain          50    7,000   1500   1700   +200    13.3      180,000  slow (vol in window, ROI < 20)
# Slow mid-roi        70    6,000   2000   2360   +360    18.0      400,000  slow (vol in window, ROI < 20)
# Slow mirage        100    7,000  12000  20000  +8000    66.7    4,800,000  excluded (mirage — vol qualifies)
# Slow too thin       50    1,500   1500   1700   +200    13.3       40,000  filtered (vol below 5k floor)
# Mid item            80   10,000   1000   1300   +300    30.0    1,200,000  mid (dropped)
# Bulk salvage     25000   50,000   8000   9500  +1500    18.8   12,000,000  easy (volume only)
# Loser bow         1000   50,000    100     50   -100   -50.0      -60,000  filtered (negative profit)

_RS3_PAGE_HTML = """
<h2>About</h2>
<table class="wikitable">
<tr><th>Setup</th><th>Cost</th></tr>
<tr><td>Alchemiser mk. II</td><td>1m</td></tr>
</table>

<h2>Alchables</h2>
<table class="wikitable sortable">
<tr>
  <th></th>
  <th>Item</th>
  <th>GE price</th>
  <th>High Alch</th>
  <th>Profit</th>
  <th>ROI%</th>
  <th>Limit</th>
  <th>Trade volume</th>
  <th>Max daily profit</th>
  <th>Details</th>
</tr>
""" + "".join(
    f"""
<tr>
  <td></td>
  <td><a href="/w/{name.replace(' ', '_')}">{name}</a></td>
  <td data-sort-value="{ge}">{ge:,}</td>
  <td data-sort-value="{alch}">{alch:,}</td>
  <td data-sort-value="{profit}">{profit:,}</td>
  <td data-sort-value="{roi}">{roi}%</td>
  <td data-sort-value="{limit}">{limit:,}</td>
  <td data-sort-value="{vol}">{vol:,}</td>
  <td data-sort-value="{mdp}">{mdp:,}</td>
  <td>view</td>
</tr>
"""
    for name, ge, alch, profit, roi, limit, vol, mdp in [
        ("Easy A",         2000,  2400,    400,   20.0,   200, 20000,  8000000),
        ("Easy B",         2000,  2300,    300,   15.0,   150, 18000,  6000000),
        ("Easy C",         2000,  2350,    350,   17.5,   120, 14000,  7000000),
        ("Slow plain",     1500,  1700,    200,   13.3,    50,  7000,   180000),
        ("Slow mid-roi",   2000,  2360,    360,   18.0,    70,  6000,   400000),
        ("Slow mirage",    12000, 20000,   8000,  66.7,   100,  7000,  4800000),
        ("Slow too thin",  1500,  1700,    200,   13.3,    50,  1500,    40000),
        ("Capped easy",    3000,  3700,    500,   16.7,    70, 30000,  4000000),
        ("Mid item",       1000,  1300,    300,   30.0,    80, 10000,  1200000),
        ("Bulk salvage",   8000,  9500,    1500,  18.8, 25000, 50000, 12000000),
        ("Loser bow",      100,   50,     -100,  -50.0,  1000, 50000,   -60000),
    ]
) + "</table>"


def _rs3_fake(html_text=_RS3_PAGE_HTML):
    async def fake_http_get(url, params=None, timeout=10.0):
        return {"parse": {"text": html_text}}
    return fake_http_get


class TestGetBestAlchablesRs3:
    @pytest.mark.anyio
    async def test_passive_default_renders_two_tables(self, monkeypatch):
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3")
        assert "**Best Alchables (RS3)** — passive" in result
        assert "🟢 Easy buys" in result
        assert "🟡 Slow buys" in result
        # Slow listed last in passive mode (per user request).
        assert result.index("🟢 Easy buys") < result.index("🟡 Slow buys")

    @pytest.mark.anyio
    async def test_passive_easy_sort_by_mdp(self, monkeypatch):
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3")
        easy_section, _, _slow = result.partition("🟡 Slow buys")
        # Easy is now buy_limit-agnostic, so Bulk salvage (limit 25000, MDP 12M)
        # is the new top entry. MDP order: Bulk salvage (12M) > Easy A (8M) > Easy C (7M).
        bs = easy_section.find("Bulk salvage")
        ea = easy_section.find("Easy A")
        ec = easy_section.find("Easy C")
        for pos in (bs, ea, ec):
            assert pos != -1
        assert bs < ea < ec

    @pytest.mark.anyio
    async def test_passive_slow_excludes_mirages_and_thin_volume(self, monkeypatch):
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3")
        _, _, slow_section = result.partition("🟡 Slow buys")
        # Slow mirage (ROI 66.7%) — excluded by ROI cap.
        # Slow too thin (vol 1,500) — excluded by the 5k volume floor.
        # Remaining slow items by MDP: Slow mid-roi (400k), Slow plain (180k).
        # buy_limit no longer constrains Slow → low-limit items still qualify.
        assert "Slow mirage" not in slow_section
        assert "Slow too thin" not in slow_section
        smr = slow_section.find("Slow mid-roi")
        sp = slow_section.find("Slow plain")
        assert smr != -1 and sp != -1
        assert smr < sp
        assert "⚠️" not in result

    @pytest.mark.anyio
    async def test_easy_requires_high_buy_limit_rs3(self, monkeypatch):
        # "Capped easy" has vol 30,000 (very high) but limit 70 — must NOT appear
        # in Easy. Since vol is also above the slow window, it gets filtered.
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3")
        assert "Capped easy" not in result

    @pytest.mark.anyio
    async def test_high_buy_limit_allowed_in_easy_only(self, monkeypatch):
        # Bulk salvage has limit=25,000 — disallowed for Slow, allowed for Easy.
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3")
        easy_section, _, slow_section = result.partition("🟡 Slow buys")
        assert "Bulk salvage" in easy_section
        assert "Bulk salvage" not in slow_section

    @pytest.mark.anyio
    async def test_mid_bucket_dropped(self, monkeypatch):
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3")
        # Mid item has volume 10,000 (between 8k and 13k) → dropped.
        assert "Mid item" not in result

    @pytest.mark.anyio
    async def test_negative_profit_filtered(self, monkeypatch):
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3")
        assert "Loser bow" not in result

    @pytest.mark.anyio
    async def test_manual_mode_mixed_table(self, monkeypatch):
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake())
        result = await get_best_alchables(game="rs3", mode="manual")
        assert "**Best Alchables (RS3)** — manual" in result
        assert "🟢 Easy buys" not in result
        assert "🟡 Slow buys" not in result
        # Top 3 easy by profit/cast: Bulk salvage (1500), Easy A (400), Easy C (350).
        # Top 2 slow by profit/cast (mirages excluded):
        #   Slow mid-roi (360), Slow plain (200).
        # Merged + sorted by profit: Bulk salvage, Easy A, Slow mid-roi, Easy C, Slow plain.
        bs = result.find("Bulk salvage")
        ea = result.find("Easy A")
        smr = result.find("Slow mid-roi")
        ec = result.find("Easy C")
        sp = result.find("Slow plain")
        for pos in (bs, ea, smr, ec, sp):
            assert pos != -1
        assert bs < ea < smr < ec < sp
        # Mirage must be silently excluded.
        assert "Slow mirage" not in result
        assert "⚠️" not in result

    @pytest.mark.anyio
    async def test_page_not_found(self, monkeypatch):
        async def fake(url, params=None, timeout=10.0):
            return {}
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", fake)
        result = await get_best_alchables(game="rs3")
        assert "Could not load the Alchemiser" in result

    @pytest.mark.anyio
    async def test_no_easy_or_slow_items(self, monkeypatch):
        # Every item lifted into the mid-bucket (volume in [8k, 13k]).
        nothing = _RS3_PAGE_HTML
        for v in ("20000", "18000", "14000", "7000", "6000", "1500", "10000", "30000", "50000"):
            nothing = nothing.replace(f'data-sort-value="{v}"', 'data-sort-value="10000"')
        monkeypatch.setattr("rs_mcp_server.tools.alchables.http_get", _rs3_fake(nothing))
        result = await get_best_alchables(game="rs3")
        assert "No items" in result
