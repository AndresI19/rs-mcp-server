"""get_item_drop_sources tool — wiki "Item sources" table for an item.

The wiki's {{Drop sources|<item>}} template is server-rendered into a sortable
table; raw wikitext alone doesn't expose the source list. We fetch the rendered
HTML via action=parse and parse the table by its `item-drops` class.
"""
import html
import re

import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get

_TTL_DROPS = 3600
_TOP_N = 3


@instrument("get_item_drop_sources")
async def get_item_drop_sources(item_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not item_name.strip():
        return "No item name provided."

    cache_key = f"drops:{game}:{item_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = await _fetch_and_format(item_name, game)
    cache.set(cache_key, result, _TTL_DROPS)
    return result


async def _fetch_and_format(item_name: str, game: str) -> str:
    wiki_label = "RS3" if game == "rs3" else "OSRS"

    page = await _fetch_page(item_name, game)
    if page is None:
        return f"Item '{item_name}' not found on the {wiki_label} Wiki."

    canonical_title = page["title"]
    page_url = f"{WIKI_BASE_URLS[game]}{canonical_title.replace(' ', '_')}"

    table = _find_item_sources_table(page["html"])
    if table is None:
        return (
            f"No drop sources recorded for '{canonical_title}' on the {wiki_label} Wiki.\n"
            f"{page_url}"
        )

    rows = _parse_rows(table)
    return _format_output(canonical_title, page_url, wiki_label, rows)


async def _fetch_page(item_name: str, game: str) -> dict | None:
    params = {
        "action": "parse",
        "page": item_name,
        "prop": "text",
        "redirects": 1,
        **MW_BASE_PARAMS,
    }
    try:
        data = await http_get(WIKI_APIS[game], params=params)
    except httpx.HTTPError:
        return None
    if "error" in data:
        return None
    parse = data.get("parse")
    if not parse:
        return None
    return {
        "title": parse.get("title", item_name),
        "html":  parse.get("text", ""),
    }


def _find_item_sources_table(html_text: str) -> str | None:
    m = re.search(
        r'<table[^>]*class="[^"]*\bitem-drops\b[^"]*"[^>]*>(.*?)</table>',
        html_text,
        re.DOTALL,
    )
    return m.group(1) if m else None


def _parse_rows(table_body: str) -> list[dict]:
    rows: list[dict] = []
    for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", table_body, re.DOTALL):
        tr_body = tr_match.group(1)
        if re.search(r"<th\b", tr_body):
            continue
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", tr_body, re.DOTALL)
        if len(cells) < 4:
            continue

        source_html = cells[0][1]
        level_attrs = cells[1][0]
        qty_html    = cells[2][1]
        rarity_html = cells[3][1]

        source, version = _extract_source(source_html)
        if not source:
            continue

        rows.append({
            "source":   source,
            "version":  version,
            "level":    _extract_level(level_attrs),
            "quantity": _strip_tags(qty_html) or "?",
            "rarity":   _extract_rarity(rarity_html),
        })
    return rows


def _extract_source(cell_html: str) -> tuple[str, str]:
    anchor = re.search(r'<a[^>]*title="([^"]+)"[^>]*>(.*?)</a>', cell_html, re.DOTALL)
    if not anchor:
        return _strip_tags(cell_html), ""
    title = html.unescape(anchor.group(1)).strip()
    version_match = re.search(r'<span class="beast-version">([^<]+)</span>', anchor.group(2))
    version = html.unescape(version_match.group(1)).strip() if version_match else ""
    return title, version


def _extract_level(attrs: str) -> str | None:
    if "table-na" in attrs:
        return None
    val = _extract_sort_value(attrs)
    if val is None or val == 0:
        return None
    return str(val)


def _extract_rarity(cell_html: str) -> str:
    m = re.search(r'data-drop-fraction="([^"]+)"', cell_html)
    if m:
        return m.group(1)
    return _strip_tags(cell_html) or "?"


def _format_output(item_name: str, page_url: str, wiki_label: str, rows: list[dict]) -> str:
    if not rows:
        return (
            f"No drop sources recorded for '{item_name}' on the {wiki_label} Wiki.\n"
            f"{page_url}"
        )

    lines = [f"**Drop sources for {item_name}** ({wiki_label} Wiki)", page_url, "", "**Top sources:**"]
    shown = rows[:_TOP_N]
    for i, r in enumerate(shown, start=1):
        lines.append(f"  {i}. {_format_row(r)}")

    remaining = len(rows) - len(shown)
    if remaining > 0:
        plural = "source" if remaining == 1 else "sources"
        lines.append("")
        lines.append(f"({remaining} more {plural} — common loot. Run `search_wiki` for the full list.)")

    return "\n".join(lines)


def _format_row(r: dict) -> str:
    name = r["source"]
    if r["version"]:
        name = f"{name} ({r['version']})"
    if r["level"]:
        return f"{name} — {r['rarity']} from a level-{r['level']} monster, qty {r['quantity']}"
    return f"{name} — {r['rarity']} drop, qty {r['quantity']}"


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_sort_value(attrs: str) -> int | None:
    m = re.search(r'data-sort-value="([^"]+)"', attrs)
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except ValueError:
        return None
