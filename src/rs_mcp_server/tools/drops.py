"""get_item_drop_sources tool — wiki "Item sources" table for an item.

The wiki's {{Drop sources|<item>}} template is server-rendered into a sortable
table; raw wikitext alone doesn't expose the source list. We fetch the rendered
HTML via action=parse and walk the `item-drops` table with html.parser — a
depth-tracking state machine, so nested tables (which a regex scan mis-splits at
the first </table> or </tr>) are handled correctly.
"""

import html
from html.parser import HTMLParser

import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import *
from ._http import http_get
from ._wiki_parsing import TableScope, collapse_whitespace as _collapse

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
    cache.set(cache_key, result, TTL_HOUR)
    return result


async def _fetch_and_format(item_name: str, game: str) -> str:
    wiki_label = WIKI_LABELS[game]

    page = await _fetch_page(item_name, game)
    if page is None:
        return f"Item '{item_name}' not found on the {wiki_label} Wiki."

    canonical_title = page["title"]
    page_url = f"{WIKI_BASE_URLS[game]}{canonical_title.replace(' ', '_')}"

    rows = _parse_drop_rows(page["html"])
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
        "html": parse.get("text", ""),
    }


# ---------------------------------------------------------------------------
# HTML parsing — extract data rows from the `item-drops` table
# ---------------------------------------------------------------------------


class _DropsTableParser(HTMLParser):
    """Collect data rows from the first `item-drops` table.

    Per row it captures only what the formatter needs: the source name (anchor
    ``title``), an optional beast version, the level (``data-sort-value`` on the
    level cell), the quantity text, and the rarity (``data-drop-fraction``).
    Table nesting is tracked by depth so the target table closes at its matching
    ``</table>`` rather than the first one encountered.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._scope = TableScope(lambda cls: "item-drops" in cls)
        self._row: dict | None = None
        self._row_has_th = False
        self._cell = -1
        self._capture_version = False

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag == "table":
            self._scope.open_table(ad)
            return
        if not self._scope.at_target_level():
            return  # outside the target table, or in a table nested in a cell
        if tag == "tr":
            self._row = {
                "source": "",
                "version": "",
                "level": None,
                "quantity": "",
                "rarity": "",
                "_src_title": None,
                "_rarity_fraction": None,
            }
            self._row_has_th = False
            self._cell = -1
        elif tag == "th":
            self._row_has_th = True
        elif tag == "td":
            self._cell += 1
            if self._row is not None and self._cell == 1:
                self._row["level"] = _level_from_attrs(ad)
        elif self._row is None or self._cell < 0:
            return
        elif self._cell == 0 and tag == "a" and self._row["_src_title"] is None:
            self._row["_src_title"] = ad.get("title")
        elif (
            self._cell == 0 and tag == "span" and "beast-version" in (ad.get("class") or "").split()
        ):
            self._capture_version = True
        elif (
            self._cell == 3 and "data-drop-fraction" in ad and self._row["_rarity_fraction"] is None
        ):
            self._row["_rarity_fraction"] = ad["data-drop-fraction"]

    def handle_data(self, data):
        if not self._scope.at_target_level() or self._row is None or self._cell < 0:
            return
        if self._capture_version:
            self._row["version"] += data
        elif self._cell == 0:
            self._row["source"] += data
        elif self._cell == 2:
            self._row["quantity"] += data
        elif self._cell == 3:
            self._row["rarity"] += data

    def handle_endtag(self, tag):
        if tag == "table":
            self._scope.close_table()
            return
        if not self._scope.at_target_level():
            return
        if tag == "span":
            self._capture_version = False
        elif tag == "tr" and self._row is not None:
            if not self._row_has_th and self._cell >= 3:
                self.rows.append(_finalize_row(self._row))
            self._row = None


def _parse_drop_rows(html_text: str) -> list[dict]:
    parser = _DropsTableParser()
    parser.feed(html_text)
    return parser.rows


def _finalize_row(row: dict) -> dict:
    source = html.unescape(row["_src_title"] or _collapse(row["source"])).strip()
    return {
        "source": source,
        "version": _collapse(row["version"]),
        "level": row["level"],
        "quantity": _collapse(row["quantity"]) or "?",
        "rarity": row["_rarity_fraction"] or _collapse(row["rarity"]) or "?",
    }


def _level_from_attrs(attrs: dict) -> str | None:
    if "table-na" in (attrs.get("class") or "").split():
        return None
    raw = attrs.get("data-sort-value")
    if raw is None:
        return None
    try:
        val = int(float(raw))
    except ValueError:
        return None
    return str(val) if val != 0 else None


def _format_output(item_name: str, page_url: str, wiki_label: str, rows: list[dict]) -> str:
    if not rows:
        return f"No drop sources recorded for '{item_name}' on the {wiki_label} Wiki.\n{page_url}"

    lines = [
        f"**Drop sources for {item_name}** ({wiki_label} Wiki)",
        page_url,
        "",
        "**Top sources:**",
    ]
    shown = rows[:_TOP_N]
    for i, r in enumerate(shown, start=1):
        lines.append(f"  {i}. {_format_row(r)}")

    remaining = len(rows) - len(shown)
    if remaining > 0:
        plural = "source" if remaining == 1 else "sources"
        lines.append("")
        lines.append(
            f"({remaining} more {plural} — common loot. Run `search_wiki` for the full list.)"
        )

    return "\n".join(lines)


def _format_row(r: dict) -> str:
    name = r["source"]
    if r["version"]:
        name = f"{name} ({r['version']})"
    if r["level"]:
        return f"{name} — {r['rarity']} from a level-{r['level']} monster, qty {r['quantity']}"
    return f"{name} — {r['rarity']} drop, qty {r['quantity']}"
