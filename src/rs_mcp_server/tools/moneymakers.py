"""Money-maker tools — RuneScape Wiki Money Making Guide pages.

Two tools:
- get_money_makers: ranks the master MMG page's hourly profit table.
- get_money_maker_method: drill-down on a single method's subpage Mmgtable template.
"""
import html
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get

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


def _parse_master_html(html_text: str, game: str) -> list[dict]:
    """Find the first wikitable sortable (the main hourly-profit table) and parse rows."""
    table_match = re.search(
        r'<table[^>]*class="[^"]*wikitable sortable[^"]*"[^>]*>(.*?)</table>',
        html_text,
        re.DOTALL,
    )
    if not table_match:
        return []
    body = table_match.group(1)

    header_html = re.findall(r"<th[^>]*>(.*?)</th>", body, re.DOTALL)
    headers = [_strip_tags(h).strip().lower() for h in header_html]
    if not headers:
        return []

    # Map normalised header → column index. Header text varies between games
    # (e.g. "Skills" vs "Skills required"); match on prefix.
    col_index = {}
    for i, h in enumerate(headers):
        for canonical in ("method", "hourly profit", "profit", "skills", "category", "intensity", "members"):
            if h.startswith(canonical) and canonical not in col_index:
                col_index[canonical] = i
                break

    rows: list[dict] = []
    for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL):
        cells_raw = re.findall(r"<td([^>]*)>(.*?)</td>", tr_match.group(1), re.DOTALL)
        if not cells_raw:
            continue

        method_idx = col_index.get("method")
        profit_idx = col_index.get("hourly profit", col_index.get("profit"))
        if method_idx is None or profit_idx is None:
            continue
        if method_idx >= len(cells_raw) or profit_idx >= len(cells_raw):
            continue

        method_attrs, method_html = cells_raw[method_idx]
        profit_attrs, profit_html = cells_raw[profit_idx]

        name, url = _extract_method_link(method_html, game)
        if not name:
            continue

        profit_value = _extract_sort_value(profit_attrs)
        if profit_value is None:
            profit_value = _strip_commas_to_int(_strip_tags(profit_html))
        profit_text = _strip_tags(profit_html).strip() or "?"

        row = {
            "name": name,
            "url": url,
            "profit_value": profit_value if profit_value is not None else 0,
            "profit_text": profit_text,
            "skills": _strip_tags(cells_raw[col_index["skills"]][1]).strip() if "skills" in col_index and col_index["skills"] < len(cells_raw) else "",
            "category": _strip_tags(cells_raw[col_index["category"]][1]).strip() if "category" in col_index and col_index["category"] < len(cells_raw) else "",
            "intensity": _strip_tags(cells_raw[col_index["intensity"]][1]).strip() if "intensity" in col_index and col_index["intensity"] < len(cells_raw) else "",
            "members": _is_members_cell(cells_raw[col_index["members"]][1]) if "members" in col_index and col_index["members"] < len(cells_raw) else None,
        }
        rows.append(row)
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
    return (
        f'Did you mean **"{display_name}"** ({wiki_label} Wiki)?\n'
        f"{url}\n\n"
        f'Re-invoke `get_money_maker_method` with method_name="{display_name}" to fetch the details.'
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


def _enumerate_io(fields: dict, prefix: str):
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

def _titles_match(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, _TTL)
    return value


async def _fetch_page(title: str, game: str, follow_redirects: bool) -> dict | None:
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions|info",
        "rvprop": "content",
        "rvslots": "main",
        "inprop": "url",
        **MW_BASE_PARAMS,
    }
    if follow_redirects:
        params["redirects"] = 1
    data = await http_get(WIKI_APIS[game], params=params)
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    page = pages[0]
    if page.get("missing"):
        return None
    revisions = page.get("revisions", [])
    if not revisions:
        return None
    content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
    resolved_title = page.get("title", title)
    return {
        "title": resolved_title,
        "url": f"{WIKI_BASE_URLS[game]}{resolved_title.replace(' ', '_')}",
        "content": content,
    }


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


def _find_template(wikitext: str, name: str) -> str | None:
    pattern = r"\{\{" + re.escape(name) + r"\b"
    match = re.search(pattern, wikitext, re.IGNORECASE)
    if not match:
        return None
    i = match.end()
    depth = 2
    while i < len(wikitext) and depth > 0:
        if wikitext[i:i + 2] == "{{":
            depth += 2
            i += 2
        elif wikitext[i:i + 2] == "}}":
            depth -= 2
            i += 2
        else:
            i += 1
    if depth != 0:
        return None
    return wikitext[match.end():i - 2]


def _parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    parts = re.split(r"\n\s*\|", "\n|" + body)
    for part in parts[1:]:
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        key = name.strip().lower()
        value = value.strip()
        if value:
            fields[key] = value
    return fields


def _clean_wikitext(s: str) -> str:
    s = re.sub(r"\{\{(?:Skillreq|SCP|mmgreq)\|([^|}]+)\|(\d+)[^}]*\}\}", r"Level \2 \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{plinkp?\|([^|}]+)[^}]*\}\}", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<br ?/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Master-page HTML helpers
# ---------------------------------------------------------------------------

def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_sort_value(attrs: str) -> int | None:
    m = re.search(r'data-sort-value="([^"]+)"', attrs)
    if not m:
        return None
    raw = m.group(1)
    try:
        return int(float(raw))
    except ValueError:
        return None


def _strip_commas_to_int(s: str) -> int | None:
    s = s.replace(",", "").strip()
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _extract_method_link(cell_html: str, game: str) -> tuple[str, str]:
    m = re.search(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', cell_html)
    if not m:
        text = _strip_tags(cell_html)
        return text, ""
    href, text = m.group(1), html.unescape(m.group(2)).strip()
    if href.startswith("/"):
        url = WIKI_BASE_URLS[game].rstrip("/w/") + href
    else:
        url = href
    return text, url


def _is_members_cell(cell_html: str) -> bool:
    return bool(re.search(r'<img[^>]+alt="[^"]*member', cell_html, re.IGNORECASE))
