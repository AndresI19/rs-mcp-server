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
import html
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument
from ._http import http_get, MW_BASE_PARAMS, WIKI_APIS
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


def _parse_rs3_table(html_text: str) -> list[dict] | None:
    """Parse the per-item alchables table on the Alchemiser mk. II wiki page."""
    tables = re.findall(
        r'<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>',
        html_text,
        re.DOTALL,
    )
    target = None
    for body in tables:
        ths = re.findall(r"<th[^>]*>(.*?)</th>", body, re.DOTALL)
        headers = [_strip_tags(h).strip().lower() for h in ths]
        if "item" in headers and "high alch" in headers and "max daily profit" in headers:
            target = (body, headers)
            break
    if target is None:
        return None

    body, headers = target

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
    for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL):
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", tr.group(1), re.DOTALL)
        if not cells:
            continue
        if any(col_index[k] >= len(cells) for k in required):
            continue

        name = _extract_link_text(cells[col_index["item"]][1]) or _strip_tags(cells[col_index["item"]][1])
        if not name:
            continue

        profit = _sort_value_float(cells[col_index["profit"]][0])
        if profit is None or profit <= 0:
            continue

        ge_price = _sort_value_int(cells[col_index["ge price"]][0]) if "ge price" in col_index else None
        high_alch = _sort_value_int(cells[col_index["high alch"]][0])
        roi = _sort_value_float(cells[col_index["roi%"]][0]) if "roi%" in col_index else None
        buy_limit = _sort_value_int(cells[col_index["limit"]][0]) if "limit" in col_index else None
        volume = _sort_value_int(cells[col_index["trade volume"]][0])
        max_daily = _sort_value_int(cells[col_index["max daily profit"]][0])

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

def _render_passive_two_tables(easy: list[dict], slow: list[dict], page_url: str) -> str:
    title = "**Best Alchables (RS3)** — passive (Alchemiser mk. II)"
    lines = [title, page_url, ""]

    # Both tables: max_daily_profit primary, ROI tiebreaker.
    sort_key = lambda r: (-r["max_daily"], -r["roi"])  # noqa: E731
    top_easy = sorted(easy, key=sort_key)[:_EASY_TOP_N]
    top_slow = sorted(slow, key=sort_key)[:_SLOW_TOP_N]

    lines.append(f"### 🟢 Easy buys — top {_EASY_TOP_N} by max daily profit")
    if top_easy:
        lines.append("| # | Item | GE Price | High Alch | Profit/cast | Max daily profit | Volume | Limit | ROI% |")
        lines.append("|---|------|----------|-----------|-------------|------------------|--------|-------|------|")
        for rank, r in enumerate(top_easy, start=1):
            lines.append(
                f"| {rank} | {r['name']} | {r['ge_price']:,} | {r['highalch']:,} | "
                f"+{int(round(r['profit'])):,} | {r['max_daily']:,} | "
                f"{r['volume']:,} | {r['buy_limit']:,} | {r['roi']:.1f}% |"
            )
    else:
        lines.append("_No items qualify as easy buys right now._")

    lines.append("")
    lines.append(f"### 🟡 Slow buys — top {_SLOW_TOP_N} by max daily profit")
    if top_slow:
        lines.append("| # | Item | GE Price | High Alch | Profit/cast | Max daily profit | Volume | Limit | ROI% |")
        lines.append("|---|------|----------|-----------|-------------|------------------|--------|-------|------|")
        for rank, r in enumerate(top_slow, start=1):
            lines.append(
                f"| {rank} | {r['name']} | {r['ge_price']:,} | {r['highalch']:,} | "
                f"+{int(round(r['profit'])):,} | {r['max_daily']:,} | "
                f"{r['volume']:,} | {r['buy_limit']:,} | {r['roi']:.1f}% |"
            )
    else:
        lines.append("_No items qualify as slow buys right now._")

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

    sort_key = lambda r: (-r["profit"], -r["roi"])  # noqa: E731
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
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
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
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(footer)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_link_text(cell_html: str) -> str:
    m = re.search(r'<a[^>]*>([^<]+)</a>', cell_html)
    if m:
        return html.unescape(m.group(1)).strip()
    return ""


def _sort_value_float(attrs: str) -> float | None:
    m = re.search(r'data-sort-value="([^"]+)"', attrs)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _sort_value_int(attrs: str) -> int | None:
    v = _sort_value_float(attrs)
    if v is None:
        return None
    return int(v)
