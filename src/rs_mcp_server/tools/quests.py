"""get_quest_info tool — RuneScape Wiki quest data via MediaWiki API."""
import re
from rs_mcp_server import cache
from rs_mcp_server.logging import instrument
from ._http import http_get, WIKI_APIS, WIKI_BASE_URLS, MW_BASE_PARAMS

_TTL = 3600  # 1 hour — matches wiki lookup bucket

_TEMPLATES = ("Infobox Quest", "Quest details")

_FIELDS = (
    ("Difficulty", "difficulty"),
    ("Length", "length"),
    ("Members", "members"),
    ("Quest series", "series"),
    ("Quest series", "main_series"),
    ("Start point", "start"),
    ("Requirements", "requirements"),
    ("Items required", "items"),
    ("Recommended", "recommended"),
    ("Rewards", "rewards"),
)


@instrument("get_quest_info")
async def get_quest_info(quest_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

    cache_key = f"quest:{game}:{quest_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = "RS3" if game == "rs3" else "OSRS"

    direct = await _fetch_page(quest_name, game, follow_redirects=True)
    if direct and _has_quest_template(direct["content"]):
        if _titles_match(quest_name, direct["title"]):
            return _cache_and_return(
                _format_from_content(direct["title"], direct["url"], wiki_label, direct["content"]),
                cache_key,
            )
        return _cache_and_return(
            _disambiguate(direct["title"], direct["url"], wiki_label),
            cache_key,
        )

    candidate = await _search_quest(quest_name, game)
    if candidate is None:
        return f"No quest found for '{quest_name}' on the {wiki_label} wiki."

    if not _titles_match(quest_name, candidate["title"]):
        return _cache_and_return(
            _disambiguate(candidate["title"], candidate["url"], wiki_label),
            cache_key,
        )

    page = await _fetch_page(candidate["title"], game, follow_redirects=False)
    if page is None or not _has_quest_template(page["content"]):
        return f"**{candidate['title']}** ({wiki_label} Wiki)\n{candidate['url']}\n\nNo quest infobox found on this page — it may not be a quest."

    return _cache_and_return(
        _format_from_content(page["title"], page["url"], wiki_label, page["content"]),
        cache_key,
    )


def _titles_match(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return (
        f'Did you mean **"{title}"** ({wiki_label} Wiki)?\n'
        f"{url}\n\n"
        f'Re-invoke `get_quest_info` with quest_name="{title}" to fetch the details.'
    )


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, _TTL)
    return value


# ---------------------------------------------------------------------------
# Wiki API helpers
# ---------------------------------------------------------------------------

async def _fetch_page(title: str, game: str, follow_redirects: bool) -> dict | None:
    """Direct title lookup. Returns dict with title/url/content, or None if missing."""
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


async def _search_quest(query: str, game: str) -> dict | None:
    """Search restricted to quest pages via `incategory:Quests`. Falls back to plain search."""
    for search_term in (f'{query} incategory:"Quests"', query):
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": search_term,
            "gsrlimit": 1,
            "prop": "info",
            "inprop": "url",
            **MW_BASE_PARAMS,
        }
        data = await http_get(WIKI_APIS[game], params=params)
        pages = data.get("query", {}).get("pages", [])
        if pages:
            page = pages[0]
            title = page.get("title", "")
            return {
                "title": title,
                "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            }
    return None


# ---------------------------------------------------------------------------
# Wikitext parsing
# ---------------------------------------------------------------------------

def _has_quest_template(wikitext: str) -> bool:
    return any(_find_template(wikitext, name) is not None for name in _TEMPLATES)


def _find_template(wikitext: str, name: str) -> str | None:
    """Walk balanced braces from `{{<name>` to its matching `}}`."""
    pattern = r"\{\{" + name.replace(" ", "[ _]") + r"\b"
    match = re.search(pattern, wikitext, re.IGNORECASE)
    if not match:
        return None
    i = match.end()
    depth = 2
    while i < len(wikitext) and depth > 0:
        if wikitext[i:i+2] == "{{":
            depth += 2
            i += 2
        elif wikitext[i:i+2] == "}}":
            depth -= 2
            i += 2
        else:
            i += 1
    if depth != 0:
        return None
    return wikitext[match.end():i-2]


def _parse_fields(template_body: str) -> dict[str, str]:
    """Split on `\n|` (not bare `|`) so nested template separators don't fragment values."""
    fields: dict[str, str] = {}
    parts = re.split(r"\n\s*\|", "\n|" + template_body)
    for part in parts[1:]:
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        key = name.strip().lower()
        value = value.strip()
        if value:
            fields[key] = value
    return fields


def _merged_fields(wikitext: str) -> dict[str, str]:
    """Parse all known quest templates; later templates overwrite earlier ones."""
    merged: dict[str, str] = {}
    for name in _TEMPLATES:
        body = _find_template(wikitext, name)
        if body:
            merged.update(_parse_fields(body))
    return merged


def _format_from_content(title: str, url: str, wiki_label: str, wikitext: str) -> str:
    fields = _merged_fields(wikitext)
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]
    seen_labels: set[str] = set()
    for label, key in _FIELDS:
        if label in seen_labels:
            continue
        value = fields.get(key)
        if not value:
            continue
        cleaned = _clean_wikitext(value)
        if not cleaned:
            continue
        seen_labels.add(label)
        if "\n" in cleaned or len(cleaned) > 60:
            lines.append(f"**{label}:**")
            for sub in cleaned.split("\n"):
                if sub.strip():
                    lines.append(f"  {sub}")
        else:
            lines.append(f"**{label}:** {cleaned}")
    return "\n".join(lines)


def _clean_wikitext(s: str) -> str:
    s = re.sub(r"\{\{Skillreq\|([^|}]+)\|(\d+)[^}]*\}\}", r"Level \2 \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{plinkp?\|([^|}]+)[^}]*\}\}", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<br ?/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()
