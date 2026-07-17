"""Money-maker tools — RuneScape Wiki Money Making Guide pages.

Two tools:
- get_money_makers: ranks the master MMG page's hourly profit table.
- get_money_maker_method: drill-down on a single method's subpage Mmgtable template.
"""

from collections.abc import Iterator
from functools import partial
from html.parser import HTMLParser

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import *
from ._http import http_get
from ._registry import ToolSpec, game_param, normalize_game, object_schema, register
from ._wiki_parsing import (
    TableScope,
    clean_infobox_wikitext,
    disambiguate,
    fetch_page_params,
    find_template as _find_template,
    join_text,
    markdown_table,
    parse_page_response,
    parse_template_fields as _parse_fields,
    titles_match as _titles_match,
)

_MASTER_PAGE = "Money_making_guide"
_METHOD_PREFIX = "Money making guide/"

_VALID_CATEGORIES = ("combat", "skilling")

_METHOD_TEMPLATES = ("Mmgtable recurring", "Mmgtable")

# Indices into a parsed cell's link list: [href, text-fragments].
_LINK_HREF, _LINK_TEXT = 0, 1


# Tool 1: get_money_makers (master page ranking)


@instrument("get_money_makers")
async def get_money_makers(
    game: str = "rs3",
    category: str | None = None,
    members_only: bool = False,
    limit: int = 10,
) -> str:
    game, err = normalize_game(game, WIKI_APIS)
    if err:
        return err

    if category is not None:
        category = category.lower()
        if category not in _VALID_CATEGORIES:
            return f"Unknown category '{category}'. Use 'combat' or 'skilling'."

    if limit < 1:
        limit = 1
    if limit > 50:
        limit = 50

    cache_key = f"mmg:list:{game}"
    rows = cache.get(cache_key)
    if rows is None:
        rows = await _fetch_master_rows(game)
        if rows is None:
            return f"Could not load the Money Making Guide for {game.upper()}."
        cache.set(cache_key, rows, TTL_HOUR)

    return _render_master_table(rows, game, category, members_only, limit)


async def _fetch_master_rows(game: str) -> list[dict] | None:
    params = {
        "action": "parse",
        "page": _MASTER_PAGE,
        "prop": "text",
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS[game], params=params)
    text = data.get("parse", {}).get("text")
    if not text:
        return None
    return _parse_master_html(text, game)


class _MasterTableParser(HTMLParser):
    """Parse the first 'wikitable sortable' table on the MMG master page.

    Tracks table depth so it captures exactly that table's own rows, robust to a table
    nested in a cell. Per cell it records the four things the ranking needs: text, the
    data-sort-value attr, the first link, and whether a members <img> is present.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headers: list[str] = []
        self.rows: list[list[dict]] = []
        self._scope = TableScope(
            lambda cls: "wikitable" in cls and "sortable" in cls, first_only=True
        )
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._th: list[str] | None = None
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag == "table":
            self._scope.open_table(ad)
            return
        if not self._scope.at_target_level():
            return  # ignore tags inside a table nested in a cell
        if tag == "tr":
            self._row = []
        elif tag == "th":
            self._th = []
        elif tag == "td":
            self._cell = {
                "text": [],
                "sort_value": _sort_value(ad.get("data-sort-value")),
                "link": None,
                "members": False,
            }
        elif self._cell is not None:
            if tag == "a" and self._cell["link"] is None:
                self._cell["link"] = [ad.get("href", ""), []]  # [href, text-parts]
                self._in_a = True
            elif tag == "img" and "member" in (ad.get("alt") or "").lower():
                self._cell["members"] = True

    def handle_data(self, data):
        if self._th is not None:
            self._th.append(data)
        elif self._cell is not None:
            self._cell["text"].append(data)
            if self._in_a and self._cell["link"] is not None:
                self._cell["link"][1].append(data)

    def handle_endtag(self, tag):
        if tag == "table":
            self._scope.close_table()
            return
        if not self._scope.at_target_level():
            return
        if tag == "a":
            self._in_a = False
        elif tag == "th" and self._th is not None:
            self.headers.append(join_text(self._th))
            self._th = None
        elif tag == "td" and self._cell is not None:
            link = None
            if self._cell["link"] is not None:
                link = (join_text(self._cell["link"][_LINK_TEXT]), self._cell["link"][_LINK_HREF])
            self._row.append(
                {
                    "text": join_text(self._cell["text"]),
                    "sort_value": self._cell["sort_value"],
                    "link": link,
                    "members": self._cell["members"],
                }
            )
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _sort_value(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_master_html(html_text: str, game: str) -> list[dict]:
    """Rank rows from the first wikitable-sortable table on the master MMG page."""
    parser = _MasterTableParser()
    parser.feed(html_text)
    headers = [h.lower() for h in parser.headers]
    if not headers:
        return []

    # Map normalised header → column index by prefix (text varies between games,
    # e.g. "Skills" vs "Skills required").
    col_index: dict[str, int] = {}
    for i, h in enumerate(headers):
        for canonical in (
            "method",
            "hourly profit",
            "profit",
            "skills",
            "category",
            "intensity",
            "members",
        ):
            if h.startswith(canonical) and canonical not in col_index:
                col_index[canonical] = i
                break

    method_idx = col_index.get("method")
    profit_idx = col_index.get("hourly profit", col_index.get("profit"))
    if method_idx is None or profit_idx is None:
        return []

    rows: list[dict] = []
    for cells in parser.rows:
        if method_idx >= len(cells) or profit_idx >= len(cells):
            continue

        method_cell = cells[method_idx]
        if method_cell["link"] is not None:
            name, href = method_cell["link"]
            # removesuffix, not rstrip: rstrip takes a CHARACTER SET, so "/w/" would strip any
            # trailing run of '/' and 'w' — silently truncating a hostname ending in 'w'.
            origin = WIKI_BASE_URLS[game].removesuffix("/w/")
            url = origin + href if href.startswith("/") else href
        else:
            name, url = method_cell["text"], ""
        if not name:
            continue

        profit_cell = cells[profit_idx]
        profit_value = profit_cell["sort_value"]
        if profit_value is None:
            profit_value = _strip_commas_to_int(profit_cell["text"])

        rows.append(
            {
                "name": name,
                "url": url,
                "profit_value": profit_value if profit_value is not None else 0,
                "profit_text": profit_cell["text"] or "?",
                "skills": _cell_field(cells, col_index, "skills", "text", ""),
                "category": _cell_field(cells, col_index, "category", "text", ""),
                "intensity": _cell_field(cells, col_index, "intensity", "text", ""),
                "members": _cell_field(cells, col_index, "members", "members", None),
            }
        )
    return rows


def _cell_field(cells: list[dict], col_index: dict[str, int], key: str, attr: str, default):
    """Value of cells[col_index[key]][attr], or `default` when that column is absent
    from this row/table (header missing, or the row has fewer cells than expected)."""
    i = col_index.get(key)
    if i is not None and i < len(cells):
        return cells[i][attr]
    return default


def _render_master_table(
    rows: list[dict], game: str, category: str | None, members_only: bool, limit: int
) -> str:
    wiki_label = WIKI_LABELS[game]
    page_url = f"{WIKI_BASE_URLS[game]}{_MASTER_PAGE}"
    has_category = any(r["category"] for r in rows)
    has_intensity = any(r["intensity"] for r in rows)
    has_members = any(r["members"] is not None for r in rows)

    notes: list[str] = []

    filtered = rows
    if members_only:
        if has_members:
            filtered = [r for r in filtered if r["members"]]
        else:
            notes.append(
                "*Note: members-only flag not surfaced on this wiki's master page; filter ignored.*"
            )

    if category in ("combat", "skilling"):
        if has_category:
            want_combat = category == "combat"
            filtered = [
                r for r in filtered if r["category"].lower().startswith("combat") == want_combat
            ]
        else:
            notes.append(
                f"*Note: category filtering not available on {wiki_label} master page; "
                f"results not filtered. Use `get_money_maker_method` to see a specific method's category.*"
            )

    filtered = sorted(filtered, key=lambda r: r["profit_value"], reverse=True)[:limit]

    lines = [f"**Hourly profit money-making methods ({wiki_label})**", page_url, ""]
    if notes:
        lines.extend(notes)
        lines.append("")

    cols = ["Rank", "Method", "GP/hr"]
    if has_category:
        cols.append("Category")
    if has_intensity:
        cols.append("Intensity")
    cols.append("Skills")
    if has_members:
        cols.append("Members")

    if not filtered:
        table_rows = [["–", "_no methods match the filters_", "–"] + ["–"] * (len(cols) - 3)]
    else:
        table_rows = []
        for rank, r in enumerate(filtered, start=1):
            link = f"[{r['name']}]({r['url']})"
            cells = [str(rank), link, r["profit_text"]]
            if has_category:
                cells.append(r["category"] or "–")
            if has_intensity:
                cells.append(r["intensity"] or "–")
            skills = (r["skills"] or "–").replace("\n", " ").replace("|", "/")
            if len(skills) > 60:
                skills = skills[:57] + "…"
            cells.append(skills)
            if has_members:
                cells.append("✓" if r["members"] else "")
            table_rows.append(cells)

    lines += markdown_table(cols, table_rows)
    return "\n".join(lines)


# Tool 2: get_money_maker_method (subpage drill-down)


@instrument("get_money_maker_method")
async def get_money_maker_method(method_name: str, game: str = "rs3") -> str:
    game, err = normalize_game(game, WIKI_APIS)
    if err:
        return err
    if not method_name.strip():
        return "No method name provided."

    cache_key = f"mmg:method:{game}:{method_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = WIKI_LABELS[game]

    result = await _method_from_direct(method_name, game, wiki_label) or await _method_from_search(
        method_name, game, wiki_label
    )
    if result is None:
        return f"No money-making method found for '{method_name}' on the {wiki_label} wiki."
    return cache.set_and_return(cache_key, result, TTL_HOUR)


async def _method_from_direct(method_name: str, game: str, wiki_label: str) -> str | None:
    """Direct subpage lookup under the 'Money making guide/' prefix."""
    direct = await _fetch_page(f"{_METHOD_PREFIX}{method_name}", game, follow_redirects=True)
    if direct is None:
        return None
    body, template_name = _find_method_template(direct["content"])
    if body is None:
        return None
    display_name = direct["title"].removeprefix(_METHOD_PREFIX)
    if _titles_match(method_name, display_name):
        return _render_method(
            display_name, direct["url"], wiki_label, _parse_fields(body), template_name
        )
    return _disambiguate_method(display_name, direct["url"], wiki_label)


async def _method_from_search(method_name: str, game: str, wiki_label: str) -> str | None:
    """Search fallback: disambiguate a near-title, else fetch + render the method page."""
    candidate = await _search_method(method_name, game)
    if candidate is None:
        return None
    display_name = candidate["title"].removeprefix(_METHOD_PREFIX)
    if not _titles_match(method_name, display_name):
        return _disambiguate_method(display_name, candidate["url"], wiki_label)

    # _search_method returns title/url only; re-fetch to get the page wikitext.
    page = await _fetch_page(candidate["title"], game, follow_redirects=False)
    if page is None:
        return None
    body, template_name = _find_method_template(page["content"])
    if body is None:
        return (
            f"**{display_name}** ({wiki_label} Wiki)\n"
            f"{page['url']}\n\n"
            f"Page exists but no Mmgtable template found — it may not be a money-making method."
        )
    return _render_method(display_name, page["url"], wiki_label, _parse_fields(body), template_name)


def _disambiguate_method(display_name: str, url: str, wiki_label: str) -> str:
    return disambiguate(
        display_name, url, wiki_label, "get_money_maker_method", "method_name", "details"
    )


def _render_method(name: str, url: str, wiki_label: str, fields: dict, template_name: str) -> str:
    lines = [f"**{name}** ({wiki_label} Wiki)", url, ""]

    activity = fields.get("activity")
    if activity:
        lines.append(f"**Activity:** {_clean_wikitext(activity)}")

    for label, key in (
        ("Category", "category"),
        ("Intensity", "intensity"),
        ("Members", "members"),
        ("Location", "location"),
        ("Recurrence time", "recurrence time"),
    ):
        val = fields.get(key)
        if val:
            lines.append(f"**{label}:** {_clean_wikitext(val)}")

    for label, key in (
        ("Skills", "skill"),
        ("Items", "item"),
        ("Quests", "quest"),
        ("Other", "other"),
    ):
        val = fields.get(key)
        if val:
            cleaned = _clean_wikitext(val)
            if cleaned:
                lines.append(f"**{label}:**")
                for sub in cleaned.split("\n"):
                    if sub.strip():
                        lines.append(f"  {sub.strip()}")

    inputs = list(_enumerate_io(fields, "input"))
    if inputs:
        lines.append("")
        lines.append("**Inputs:**")
        for item, qty in inputs:
            prefix = f"{qty} " if qty else ""
            lines.append(f"  - {prefix}{item}")

    outputs = list(_enumerate_io(fields, "output"))
    if outputs:
        lines.append("")
        lines.append("**Outputs:**")
        for item, qty in outputs:
            prefix = f"{qty} " if qty else ""
            lines.append(f"  - {prefix}{item}")

    details = fields.get("details")
    if details:
        cleaned = _clean_wikitext(details)
        if cleaned:
            truncated = cleaned[:400] + (
                "… (see wiki for full details)" if len(cleaned) > 400 else ""
            )
            lines.append("")
            lines.append("**Details:**")
            lines.append(f"  {truncated}")

    if template_name == "Mmgtable recurring":
        lines.append("")
        lines.append("_(This is a recurring activity — see the Recurrence time field.)_")

    return "\n".join(lines)


def _enumerate_io(fields: dict[str, str], prefix: str) -> Iterator[tuple[str, str]]:
    i = 1
    while True:
        item = fields.get(f"{prefix}{i}")
        if not item:
            break
        qty = fields.get(f"{prefix}{i}num", "")
        yield _clean_wikitext(item), _clean_wikitext(qty) if qty else ""
        i += 1


def _find_method_template(wikitext: str) -> tuple[str | None, str]:
    for name in _METHOD_TEMPLATES:
        body = _find_template(wikitext, name)
        if body is not None:
            return body, name
    return None, ""


# Shared helpers (parse, fetch, search, cache)


async def _fetch_page(title: str, game: str, follow_redirects: bool) -> dict | None:
    data = await http_get(WIKI_APIS[game], params=fetch_page_params(title, follow_redirects))
    return parse_page_response(data, title, game)


async def _search_method(query: str, game: str) -> dict | None:
    """Search prefixed with `Money making guide/` so we don't return unrelated articles."""
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f'"{_METHOD_PREFIX}" {query}',
        "gsrlimit": 1,
        "prop": "info",
        "inprop": "url",
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS[game], params=params)
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    page = pages[0]
    title = page.get("title", "")
    if not title.startswith(_METHOD_PREFIX):
        return None
    return {
        "title": title,
        "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
    }


# Money-maker guides add the mmgreq level template on top of the quest set.
_clean_wikitext = partial(clean_infobox_wikitext, skillreq_templates=("Skillreq", "SCP", "mmgreq"))


def _strip_commas_to_int(s: str) -> int | None:
    s = s.replace(",", "").strip()
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


TOOL_MAKERS = register(
    ToolSpec(
        name="get_money_makers",
        description="Rank RuneScape money-making methods by hourly profit, optionally filtered by category (combat/skilling) and members status. Returns a markdown table from the wiki's Money Making Guide. Use get_money_maker_method to drill into a specific method.",
        input_schema=object_schema(
            {
                "game": game_param(
                    "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                ),
                "category": {
                    "type": "string",
                    "enum": ["combat", "skilling"],
                    "description": "Optional category filter. OSRS-only; on RS3 the filter is a no-op with a note.",
                },
                "members_only": {
                    "type": "boolean",
                    "description": "If true, restrict to members-only methods.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many top methods to return (default 10, max 50).",
                },
            },
            required=[],
        ),
        invoke=lambda args: get_money_makers(
            args.get("game", "rs3"),
            args.get("category"),
            args.get("members_only", False),
            args.get("limit", 10),
        ),
    )
)


TOOL_METHOD = register(
    ToolSpec(
        name="get_money_maker_method",
        description="Get full details about a single money-making method from the wiki — category, intensity, skills, items, quests required, inputs/outputs per hour, and a snippet of the guide details.",
        input_schema=object_schema(
            {
                "method_name": {
                    "type": "string",
                    "description": "The method name as it appears on the wiki (e.g. 'Bird house trapping').",
                },
                "game": game_param(
                    "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                ),
            },
            required=["method_name"],
        ),
        invoke=lambda args: get_money_maker_method(args["method_name"], args.get("game", "rs3")),
    )
)
