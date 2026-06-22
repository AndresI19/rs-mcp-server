"""Money-maker tools — RuneScape Wiki Money Making Guide pages.

Two tools:
- get_money_makers: ranks the master MMG page's hourly profit table.
- get_money_maker_method: drill-down on a single method's subpage Mmgtable template.
"""
import re
from collections.abc import Iterator
from html.parser import HTMLParser

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get
from ._wiki_parsing import (
    TableScope,
    disambiguate,
    fetch_page_params,
    find_template as _find_template,
    parse_page_response,
    parse_template_fields as _parse_fields,
    titles_match as _titles_match,
)

_TTL = 3600

_MASTER_PAGE = "Money_making_guide"
_METHOD_PREFIX = "Money making guide/"

_VALID_CATEGORIES = ("combat", "skilling")

_METHOD_TEMPLATES = ("Mmgtable recurring", "Mmgtable")


# ---------------------------------------------------------------------------
# Tool 1: get_money_makers (master page ranking)
# ---------------------------------------------------------------------------

@instrument("get_money_makers")
async def get_money_makers(
    game: str = "rs3",
    category: str | None = None,
    members_only: bool = False,
    limit: int = 10,
) -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

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
        cache.set(cache_key, rows, _TTL)

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

    Replaces a stack of regexes — '<table…sortable…>(.*?)</table>' then '<tr>(.*?)</tr>',
    '<td…>(.*?)</td>', plus per-cell <a>/<img>/data-sort-value scans — that were both
    fragile (the '.*?'-stops-at-first-close class) and easy to mis-read. Tracks table
    depth so it captures exactly the first sortable table's own rows (matching the old
    re.search's single-table intent, but robust to nested tables in a cell); per cell
    it records the text, the data-sort-value attr, the first link, and whether a
    members <img> is present — the four things the ranking needs.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headers: list[str] = []
        self.rows: list[list[dict]] = []
        self._scope = TableScope(lambda cls: "wikitable" in cls and "sortable" in cls, first_only=True)
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
            self._cell = {"text": [], "sort_value": _sort_value(ad.get("data-sort-value")),
                          "link": None, "members": False}
        elif self._cell is not None:
            if tag == "a" and self._cell["link"] is None:
                self._cell["link"] = [ad.get("href", ""), []]   # [href, text-parts]
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
            self.headers.append(" ".join("".join(self._th).split()))
            self._th = None
        elif tag == "td" and self._cell is not None:
            link = None
            if self._cell["link"] is not None:
                link = (" ".join("".join(self._cell["link"][1]).split()), self._cell["link"][0])
            self._row.append({
                "text": " ".join("".join(self._cell["text"]).split()),
                "sort_value": self._cell["sort_value"],
                "link": link,
                "members": self._cell["members"],
            })
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

    # Map normalised header → column index. Header text varies between games
    # (e.g. "Skills" vs "Skills required"); match on prefix.
    col_index: dict[str, int] = {}
    for i, h in enumerate(headers):
        for canonical in ("method", "hourly profit", "profit", "skills", "category", "intensity", "members"):
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
            url = WIKI_BASE_URLS[game].rstrip("/w/") + href if href.startswith("/") else href
        else:
            name, url = method_cell["text"], ""
        if not name:
            continue

        profit_cell = cells[profit_idx]
        profit_value = profit_cell["sort_value"]
        if profit_value is None:
            profit_value = _strip_commas_to_int(profit_cell["text"])

        rows.append({
            "name": name,
            "url": url,
            "profit_value": profit_value if profit_value is not None else 0,
            "profit_text": profit_cell["text"] or "?",
            "skills": cells[col_index["skills"]]["text"] if "skills" in col_index and col_index["skills"] < len(cells) else "",
            "category": cells[col_index["category"]]["text"] if "category" in col_index and col_index["category"] < len(cells) else "",
            "intensity": cells[col_index["intensity"]]["text"] if "intensity" in col_index and col_index["intensity"] < len(cells) else "",
            "members": cells[col_index["members"]]["members"] if "members" in col_index and col_index["members"] < len(cells) else None,
        })
    return rows


def _render_master_table(rows: list[dict], game: str, category: str | None, members_only: bool, limit: int) -> str:
    wiki_label = "RS3" if game == "rs3" else "OSRS"
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
            notes.append("*Note: members-only flag not surfaced on this wiki's master page; filter ignored.*")

    if category == "combat":
        if has_category:
            filtered = [r for r in filtered if r["category"].lower().startswith("combat")]
        else:
            notes.append(f"*Note: category filtering not available on {wiki_label} master page; results not filtered. Use `get_money_maker_method` to see a specific method's category.*")
    elif category == "skilling":
        if has_category:
            filtered = [r for r in filtered if not r["category"].lower().startswith("combat")]
        else:
            notes.append(f"*Note: category filtering not available on {wiki_label} master page; results not filtered. Use `get_money_maker_method` to see a specific method's category.*")

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

    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")

    if not filtered:
        lines.append("| – | _no methods match the filters_ | – |" + "| – " * (len(cols) - 3) + "|")
        return "\n".join(lines)

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
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: get_money_maker_method (subpage drill-down)
# ---------------------------------------------------------------------------

@instrument("get_money_maker_method")
async def get_money_maker_method(method_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not method_name.strip():
        return "No method name provided."

    cache_key = f"mmg:method:{game}:{method_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = "RS3" if game == "rs3" else "OSRS"
    full_title = f"{_METHOD_PREFIX}{method_name}"

    direct = await _fetch_page(full_title, game, follow_redirects=True)
    if direct is not None:
        body, template_name = _find_method_template(direct["content"])
        if body is not None:
            display_name = direct["title"].removeprefix(_METHOD_PREFIX)
            if _titles_match(method_name, display_name):
                return _cache_and_return(
                    _render_method(display_name, direct["url"], wiki_label, _parse_fields(body), template_name),
                    cache_key,
                )
            return _cache_and_return(
                _disambiguate_method(display_name, direct["url"], wiki_label),
                cache_key,
            )

    candidate = await _search_method(method_name, game)
    if candidate is None:
        return f"No money-making method found for '{method_name}' on the {wiki_label} wiki."

    candidate_display = candidate["title"].removeprefix(_METHOD_PREFIX)
    if not _titles_match(method_name, candidate_display):
        return _cache_and_return(
            _disambiguate_method(candidate_display, candidate["url"], wiki_label),
            cache_key,
        )

    page = await _fetch_page(candidate["title"], game, follow_redirects=False)
    if page is None:
        return f"No money-making method found for '{method_name}' on the {wiki_label} wiki."
    body, template_name = _find_method_template(page["content"])
    if body is None:
        return (
            f"**{candidate_display}** ({wiki_label} Wiki)\n"
            f"{page['url']}\n\n"
            f"Page exists but no Mmgtable template found — it may not be a money-making method."
        )
    return _cache_and_return(
        _render_method(candidate_display, page["url"], wiki_label, _parse_fields(body), template_name),
        cache_key,
    )


def _disambiguate_method(display_name: str, url: str, wiki_label: str) -> str:
    return disambiguate(display_name, url, wiki_label, "get_money_maker_method", "method_name", "details")


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

    for label, key in (("Skills", "skill"), ("Items", "item"), ("Quests", "quest"), ("Other", "other")):
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
            truncated = cleaned[:400] + ("… (see wiki for full details)" if len(cleaned) > 400 else "")
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


# ---------------------------------------------------------------------------
# Shared helpers (parse, fetch, search, cache)
# ---------------------------------------------------------------------------

def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, _TTL)
    return value


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


def _clean_wikitext(s: str) -> str:
    s = re.sub(r"\{\{(?:Skillreq|SCP|mmgreq)\|([^|}]+)\|(\d+)[^}]*\}\}", r"Level \2 \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{plinkp?\|([^|}]+)[^}]*\}\}", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<br ?/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _strip_commas_to_int(s: str) -> int | None:
    s = s.replace(",", "").strip()
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None
