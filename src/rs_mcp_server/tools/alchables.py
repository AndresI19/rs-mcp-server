"""get_best_alchables tool — rank items by High Alchemy profit (OSRS, RS3).

Categorization (chosen with the user, issue #42):

Universal: items must be tradeable (buy_limit > 0) — leagues-only and
NPC-only items have limit=0 in the OSRS mapping.

- Easy buy: volume > 13,000 AND buy_limit > 100. Both matter — Easy
            means "bulk-flood-friendly," which needs both a deep
            market and a per-window cap that doesn't gate you.
- Slow buy: 5,000 < volume < 8,000 AND ROI% <= 20. Buy_limit isn't
            the bottleneck for these items — when daily volume is in
            the thousands, the GE per-window limit is moot regardless
            of its value. The thin market itself defines the category.
- Items not in either bucket (incl. mid-volumes, deep-market-but-low-
  limit items, and very thin markets) are dropped.

Sort: max_daily_profit primary, ROI% tiebreaker.

Output shape per mode:
- Passive (RS3 default):
    Two tables — Easy buys (top 3) above Slow buys (top 2), each
    sorted by max_daily_profit with ROI% as tiebreaker.
- Manual (OSRS default; RS3 explicit):
    Single mixed table — top 3 easy + top 2 slow, deduped, sorted by
    profit per cast (≈ MDP for OSRS where there's no Alchemiser cap),
    with a Category column and a Mirage marker on flagged slow buys.

Daily volume sources:
- OSRS — prices.runescape.wiki /1h projected to a day.
- RS3  — Trade volume column on the Alchemiser mk. II wiki page.
"""
from html.parser import HTMLParser

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, http_get
from ._wiki_parsing import TableScope, collapse_whitespace as _collapse
from .prices import osrs_mapping

_OSRS_LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
_OSRS_1H_URL = "https://prices.runescape.wiki/api/v1/osrs/1h"
_NATURE_RUNE_ID_OSRS = 561
_RS3_PAGE = "Money_making_guide/Operating_the_Alchemiser_mk._II"

# Categorization thresholds (chosen with the user — see issue #42 thread).
_EASY_BUY_LIMIT_MIN = 100   # easy only: buy_limit must be > this (bulk-flood-friendly)
_EASY_VOLUME_MIN = 13_000   # > → easy buy
_SLOW_VOLUME_MAX = 8_000    # slow upper bound
_SLOW_VOLUME_MIN = 5_000    # slow lower bound — anything thinner can't be sourced reliably
_MIRAGE_ROI_MAX = 20.0      # slow only: ROI% > this is treated as likely mispricing → excluded

# Output sizes (per category).
_EASY_TOP_N = 3
_SLOW_TOP_N = 2

_TTL_LATEST = 300
_TTL_1H = 300
_TTL_RS3_TABLE = 3600

_VALID_MODES = ("manual", "passive")
_DEFAULT_MODE = {"osrs": "manual", "rs3": "passive"}


@instrument("get_best_alchables")
async def get_best_alchables(
    game: str = "osrs",
    members_only: bool = False,
    mode: str | None = None,
) -> str:
    game = game.lower()
    if game not in ("osrs", "rs3"):
        return f"Unknown game '{game}'. Use 'osrs' or 'rs3'."

    if mode is None:
        mode = _DEFAULT_MODE[game]
    else:
        mode = mode.lower()
        if mode not in _VALID_MODES:
            return f"Unknown mode '{mode}'. Use 'manual' or 'passive'."

    if game == "osrs":
        return await _get_best_alchables_osrs(members_only, mode)
    return await _get_best_alchables_rs3(mode)


def _categorize(item: dict) -> tuple[bool, bool]:
    """Return (is_easy, is_slow) for an item.

    Untradeable items (buy_limit <= 0) are excluded everywhere.

    Easy buys: volume > _EASY_VOLUME_MIN AND buy_limit > _EASY_BUY_LIMIT_MIN.
        Both conditions are required for "bulk-flood-friendly" — a deep
        market is moot if the per-window cap throttles acquisition.

    Slow buys: _SLOW_VOLUME_MIN < volume < _SLOW_VOLUME_MAX
        AND ROI% <= _MIRAGE_ROI_MAX. Buy_limit isn't the bottleneck for
        thin-market items (volume itself caps how fast you can source).
        The volume floor rejects items too thin to source reliably; the
        ROI cap excludes likely mispricings.

    Mid-bucket volumes (8k–13k) qualify for neither.
    """
    buy_limit = item.get("buy_limit", 0)
    if buy_limit <= 0:
        return False, False
    volume = item.get("volume", 0)
    roi = item.get("roi", 0.0)
    is_easy = volume > _EASY_VOLUME_MIN and buy_limit > _EASY_BUY_LIMIT_MIN
    is_slow = (
        _SLOW_VOLUME_MIN < volume < _SLOW_VOLUME_MAX
        and roi <= _MIRAGE_ROI_MAX
    )
    return is_easy, is_slow


def _split_pools(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Tag each row with categories and return (easy_pool, slow_pool)."""
    easy: list[dict] = []
    slow: list[dict] = []
    for r in rows:
        is_easy, is_slow = _categorize(r)
        r["is_easy"] = is_easy
        r["is_slow"] = is_slow
        if is_easy:
            easy.append(r)
        if is_slow:
            slow.append(r)
    return easy, slow


def _category_tag(r: dict) -> str:
    if r.get("is_easy"):
        return "🟢 Easy"
    if r.get("is_slow"):
        return "🟡 Slow"
    return ""


# ---------------------------------------------------------------------------
# OSRS — prices.runescape.wiki: mapping + bulk /latest + bulk /1h volumes
# ---------------------------------------------------------------------------

async def _osrs_latest_bulk() -> dict:
    cached = cache.get("osrs:latest:bulk")
    if cached is not None:
        return cached
    data = await http_get(_OSRS_LATEST_URL)
    cache.set("osrs:latest:bulk", data, _TTL_LATEST)
    return data


async def _osrs_1h_bulk() -> dict:
    cached = cache.get("osrs:1h:bulk")
    if cached is not None:
        return cached
    data = await http_get(_OSRS_1H_URL)
    cache.set("osrs:1h:bulk", data, _TTL_1H)
    return data


async def _build_osrs_rows(members_only: bool) -> tuple[list[dict] | None, int | None]:
    mapping = await osrs_mapping()
    latest_payload = await _osrs_latest_bulk()
    hourly_payload = await _osrs_1h_bulk()

    prices = latest_payload.get("data", {})
    hourly = hourly_payload.get("data", {})

    nature_info = prices.get(str(_NATURE_RUNE_ID_OSRS)) or {}
    nature_price = nature_info.get("high") or nature_info.get("low")
    if not nature_price:
        return None, None

    rows: list[dict] = []
    for item in mapping:
        highalch = item.get("highalch")
        if not highalch:
            continue
        if members_only and not item.get("members"):
            continue

        item_id = item.get("id")
        info = prices.get(str(item_id))
        if not info:
            continue
        buy = info.get("high") or info.get("low")
        if not buy:
            continue

        profit = highalch - buy - nature_price
        if profit <= 0:
            continue

        h = hourly.get(str(item_id)) or {}
        hourly_volume = (h.get("highPriceVolume") or 0) + (h.get("lowPriceVolume") or 0)
        daily_volume = hourly_volume * 24
        roi = (profit / buy) * 100 if buy else 0.0

        rows.append({
            "name": item.get("name", "?"),
            "buy": buy,
            "highalch": highalch,
            "profit": profit,
            "volume": daily_volume,
            "buy_limit": item.get("limit") or 0,
            "roi": roi,
            "members": bool(item.get("members")),
            # OSRS has no Alchemiser; max_daily is meaningless here. Leave 0
            # so the passive-on-OSRS fallback (which uses manual rendering)
            # never surfaces it.
            "max_daily": 0,
        })

    return rows, nature_price


async def _get_best_alchables_osrs(members_only: bool, mode: str) -> str:
    rows, nature_price = await _build_osrs_rows(members_only)
    if rows is None:
        return "Could not determine the current Nature rune price from the OSRS prices API."

    easy, slow = _split_pools(rows)

    # OSRS always renders the manual (mixed) layout — Alchemiser passive
    # alching has no OSRS equivalent.
    return _render_mixed(
        title=_osrs_title(members_only),
        easy_pool=easy,
        slow_pool=slow,
        passive_requested=(mode == "passive"),
        footer=(
            f"Nature rune: {nature_price:,} gp · "
            f"Easy = volume > {_EASY_VOLUME_MIN:,} AND buy_limit > {_EASY_BUY_LIMIT_MIN}. "
            f"Slow = {_SLOW_VOLUME_MIN:,} < volume < {_SLOW_VOLUME_MAX:,} "
            f"AND ROI% ≤ {int(_MIRAGE_ROI_MAX)}. "
            "Volume projected from prices.runescape.wiki /1h × 24."
        ),
        columns=("Buy", "High Alch"),
        column_keys=("buy", "highalch"),
        members_column=True,
    )


def _osrs_title(members_only: bool) -> str:
    title = "**Best Alchables (OSRS)**"
    if members_only:
        title += " — members-only"
    return title


# ---------------------------------------------------------------------------
# RS3 — Alchemiser mk. II Money Making Guide page (table[1])
# ---------------------------------------------------------------------------

async def _fetch_rs3_alchemiser_rows() -> list[dict] | None:
    cached = cache.get("rs3:alchemiser:table")
    if cached is not None:
        return cached

    params = {
        "action": "parse",
        "page": _RS3_PAGE,
        "prop": "text",
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS["rs3"], params=params)
    text = data.get("parse", {}).get("text")
    if not text:
        return None

    rows = _parse_rs3_table(text)
    if rows is None:
        return None

    cache.set("rs3:alchemiser:table", rows, _TTL_RS3_TABLE)
    return rows


class _AlchTableParser(HTMLParser):
    """Collect wikitables as {headers, rows}. Each cell exposes its
    ``data-sort-value`` (for numeric columns), first-anchor text (item name),
    and stripped text. Depth-tracking so a nested table can't corrupt rows.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self._scope = TableScope(lambda cls: "wikitable" in cls)
        self._headers: list[str] | None = None
        self._rows: list[list[dict]] | None = None
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._in_th = False
        self._th = ""
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag == "table":
            if self._scope.open_table(ad):
                self._headers = []
                self._rows = []
            return
        if not self._scope.at_target_level():
            return
        if tag == "tr":
            self._row = []
        elif tag == "th":
            self._in_th = True
            self._th = ""
        elif tag == "td":
            self._cell = {"sort": ad.get("data-sort-value"), "link": None, "text": ""}
            self._in_a = False
        elif tag == "a" and self._cell is not None and self._cell["link"] is None:
            self._in_a = True

    def handle_data(self, data):
        if not self._scope.at_target_level():
            return
        if self._in_th:
            self._th += data
        elif self._cell is not None:
            self._cell["text"] += data
            if self._in_a:
                self._cell["link"] = (self._cell["link"] or "") + data

    def handle_endtag(self, tag):
        if tag == "table":
            if self._scope.close_table():
                self.tables.append({"headers": self._headers, "rows": self._rows})
                self._headers = None
                self._rows = None
            return
        if not self._scope.at_target_level():
            return
        if tag == "th" and self._in_th:
            self._in_th = False
            self._headers.append(_collapse(self._th).lower())
        elif tag == "a":
            self._in_a = False
        elif tag == "td" and self._cell is not None and self._row is not None:
            self._cell["text"] = _collapse(self._cell["text"])
            self._cell["link"] = _collapse(self._cell["link"]) if self._cell["link"] else None
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None


def _sv_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _sv_int(value: str | None) -> int | None:
    f = _sv_float(value)
    return int(f) if f is not None else None


def _opt_sort(cells: list[dict], col_index: dict[str, int], key: str, conv) -> int | float | None:
    """Convert an optional column's data-sort-value via `conv`, or None if absent."""
    if key not in col_index:
        return None
    return conv(cells[col_index[key]]["sort"])


def _parse_rs3_table(html_text: str) -> list[dict] | None:
    """Parse the per-item alchables table on the Alchemiser mk. II wiki page."""
    parser = _AlchTableParser()
    parser.feed(html_text)

    target = None
    for table in parser.tables:
        headers = table["headers"]
        if "item" in headers and "high alch" in headers and "max daily profit" in headers:
            target = table
            break
    if target is None:
        return None

    headers = target["headers"]
    canonicals = ("item", "ge price", "high alch", "profit", "roi%", "limit", "trade volume", "max daily profit")
    col_index: dict[str, int] = {}
    for i, h in enumerate(headers):
        for canonical in canonicals:
            if h == canonical and canonical not in col_index:
                col_index[canonical] = i
                break

    required = ("item", "high alch", "profit", "trade volume", "max daily profit")
    if any(c not in col_index for c in required):
        return None

    rows: list[dict] = []
    for cells in target["rows"]:
        if not cells:
            continue
        if any(col_index[k] >= len(cells) for k in required):
            continue

        item = cells[col_index["item"]]
        name = item["link"] or item["text"]
        if not name:
            continue

        profit = _sv_float(cells[col_index["profit"]]["sort"])
        if profit is None or profit <= 0:
            continue

        ge_price = _opt_sort(cells, col_index, "ge price", _sv_int)
        high_alch = _sv_int(cells[col_index["high alch"]]["sort"])
        roi = _opt_sort(cells, col_index, "roi%", _sv_float)
        buy_limit = _opt_sort(cells, col_index, "limit", _sv_int)
        volume = _sv_int(cells[col_index["trade volume"]]["sort"])
        max_daily = _sv_int(cells[col_index["max daily profit"]]["sort"])

        if volume is None or max_daily is None or high_alch is None:
            continue

        rows.append({
            "name": name,
            "buy": ge_price or 0,           # alias used by the renderer
            "ge_price": ge_price or 0,
            "highalch": high_alch,
            "profit": profit,
            "roi": roi or 0.0,
            "buy_limit": buy_limit or 0,
            "volume": volume,
            "max_daily": max_daily,
        })

    return rows


async def _get_best_alchables_rs3(mode: str) -> str:
    rows = await _fetch_rs3_alchemiser_rows()
    if rows is None:
        return (
            "Could not load the Alchemiser mk. II Money Making Guide page. "
            "https://runescape.wiki/w/" + _RS3_PAGE
        )

    easy, slow = _split_pools(rows)
    if not easy and not slow:
        return (
            "No items on the Alchemiser mk. II page qualify as easy or slow buys "
            "right now. https://runescape.wiki/w/" + _RS3_PAGE
        )

    page_url = "https://runescape.wiki/w/" + _RS3_PAGE

    if mode == "passive":
        return _render_passive_two_tables(easy, slow, page_url)
    return _render_mixed(
        title="**Best Alchables (RS3)** — manual",
        easy_pool=easy,
        slow_pool=slow,
        passive_requested=False,
        footer=(
            f"{page_url}\n"
            f"Easy = volume > {_EASY_VOLUME_MIN:,} AND buy_limit > {_EASY_BUY_LIMIT_MIN}. "
            f"Slow = {_SLOW_VOLUME_MIN:,} < volume < {_SLOW_VOLUME_MAX:,} "
            f"AND ROI% ≤ {int(_MIRAGE_ROI_MAX)}."
        ),
        columns=("GE Price", "High Alch"),
        column_keys=("ge_price", "highalch"),
        members_column=False,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Build a markdown table (header row, separator, data rows) as a list of lines."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


_PASSIVE_COLUMNS = ["#", "Item", "GE Price", "High Alch", "Profit/cast",
                    "Max daily profit", "Volume", "Limit", "ROI%"]


def _render_alch_section(emoji: str, label: str, top_n: int, rows: list[dict]) -> list[str]:
    """Render one passive-mode section (Easy or Slow buys) as markdown table lines."""
    lines = [f"### {emoji} {label} buys — top {top_n} by max daily profit"]
    if not rows:
        lines.append(f"_No items qualify as {label.lower()} buys right now._")
        return lines
    table_rows = [
        [str(rank), r["name"], f"{r['ge_price']:,}", f"{r['highalch']:,}",
         f"+{int(round(r['profit'])):,}", f"{r['max_daily']:,}",
         f"{r['volume']:,}", f"{r['buy_limit']:,}", f"{r['roi']:.1f}%"]
        for rank, r in enumerate(rows, start=1)
    ]
    lines += _markdown_table(_PASSIVE_COLUMNS, table_rows)
    return lines


def _render_passive_two_tables(easy: list[dict], slow: list[dict], page_url: str) -> str:
    title = "**Best Alchables (RS3)** — passive (Alchemiser mk. II)"
    lines = [title, page_url, ""]

    # Both tables: max_daily_profit primary, ROI tiebreaker.
    def sort_key(r):
        return (-r["max_daily"], -r["roi"])
    top_easy = sorted(easy, key=sort_key)[:_EASY_TOP_N]
    top_slow = sorted(slow, key=sort_key)[:_SLOW_TOP_N]

    lines += _render_alch_section("🟢", "Easy", _EASY_TOP_N, top_easy)
    lines.append("")
    lines += _render_alch_section("🟡", "Slow", _SLOW_TOP_N, top_slow)

    lines.append("")
    lines.append(
        f"Easy = volume > {_EASY_VOLUME_MIN:,} AND buy_limit > {_EASY_BUY_LIMIT_MIN}. "
        f"Slow = {_SLOW_VOLUME_MIN:,} < volume < {_SLOW_VOLUME_MAX:,} "
        f"AND ROI% ≤ {int(_MIRAGE_ROI_MAX)} (slow buys with higher ROI are excluded "
        "as likely mispricings)."
    )
    return "\n".join(lines)


def _render_mixed(
    *,
    title: str,
    easy_pool: list[dict],
    slow_pool: list[dict],
    passive_requested: bool,
    footer: str,
    columns: tuple[str, str],
    column_keys: tuple[str, str],
    members_column: bool,
) -> str:
    """Single mixed table: top 3 easy + top 2 slow merged, sorted by profit/cast.

    profit/cast is primary because manual alch throughput depends on the player,
    not the Alchemiser device — multiplying by your own cast rate gives your
    real daily profit. ROI% is the tiebreaker.
    """
    lines = [title, ""]
    if passive_requested:
        lines.append(
            "_OSRS has no Alchemiser-style passive alching; ranking with the manual formula instead._"
        )
        lines.append("")

    def sort_key(r):
        return (-r["profit"], -r["roi"])
    top_easy = sorted(easy_pool, key=sort_key)[:_EASY_TOP_N]
    top_slow = sorted(slow_pool, key=sort_key)[:_SLOW_TOP_N]

    seen: set[str] = set()
    merged: list[dict] = []
    for r in top_easy + top_slow:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        merged.append(r)
    merged.sort(key=sort_key)

    if not merged:
        lines.append("_No items qualify as easy or slow buys right now._")
        lines.append("")
        lines.append(footer)
        return "\n".join(lines)

    header = ["#", "Item", columns[0], columns[1], "Profit/cast", "Volume", "Limit", "ROI%", "Category"]
    if members_column:
        header.append("P2P")
    table_rows = []
    for rank, r in enumerate(merged, start=1):
        cells = [
            str(rank),
            r["name"],
            f"{r[column_keys[0]]:,}",
            f"{r[column_keys[1]]:,}",
            f"+{int(round(r['profit'])):,}",
            f"{r['volume']:,}",
            f"{r['buy_limit']:,}",
            f"{r['roi']:.1f}%",
            _category_tag(r),
        ]
        if members_column:
            cells.append("✓" if r.get("members") else "")
        table_rows.append(cells)
    lines += _markdown_table(header, table_rows)
    lines.append("")
    lines.append(footer)
    return "\n".join(lines)


