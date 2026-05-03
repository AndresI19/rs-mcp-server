"""get_equipment_stats tool — RuneScape Wiki Infobox Bonuses (OSRS + RS3)."""
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get

_TTL = 3600

_OSRS_STATS = [
    ("Slot", "slot"),
    ("Combat style", "combatstyle"),
    ("Speed", "speed"),
    ("Attack range", "attackrange"),
    ("Attack stab", "astab"),
    ("Attack slash", "aslash"),
    ("Attack crush", "acrush"),
    ("Attack magic", "amagic"),
    ("Attack ranged", "arange"),
    ("Defence stab", "dstab"),
    ("Defence slash", "dslash"),
    ("Defence crush", "dcrush"),
    ("Defence magic", "dmagic"),
    ("Defence ranged", "drange"),
    ("Strength", "str"),
    ("Ranged strength", "rstr"),
    ("Magic damage", "mdmg"),
    ("Prayer", "prayer"),
]

_RS3_STATS = [
    ("Slot", "slot"),
    ("Class", "class"),
    ("Style", "style"),
    ("Tier", "tier"),
    ("Damage", "damage"),
    ("Accuracy", "accuracy"),
    ("Speed", "speed"),
    ("Attack range", "attack_range"),
    ("Requirements", "requirements"),
]

_STATS_BY_GAME = {"osrs": _OSRS_STATS, "rs3": _RS3_STATS}


@instrument("get_equipment_stats")
async def get_equipment_stats(item_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not item_name.strip():
        return "No item name provided."

    cache_key = f"equipment:{game}:{item_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = "RS3" if game == "rs3" else "OSRS"
    stats_def = _STATS_BY_GAME[game]

    direct = await _fetch_page(item_name, game, follow_redirects=True)
    if direct is not None:
        body = _find_template(direct["content"], "Infobox Bonuses")
        if body is not None:
            if _titles_match(item_name, direct["title"]):
                return _cache_and_return(
                    _format_stats(direct["title"], direct["url"], wiki_label, _parse_fields(body), stats_def),
                    cache_key,
                )
            return _cache_and_return(
                _disambiguate(direct["title"], direct["url"], wiki_label),
                cache_key,
            )

    candidate = await _search_item(item_name, game)
    if candidate is None:
        return f"No equipment found for '{item_name}' on the {wiki_label} wiki."

    if not _titles_match(item_name, candidate["title"]):
        return _cache_and_return(
            _disambiguate(candidate["title"], candidate["url"], wiki_label),
            cache_key,
        )

    page = await _fetch_page(candidate["title"], game, follow_redirects=False)
    if page is None:
        return f"No equipment found for '{item_name}' on the {wiki_label} wiki."
    body = _find_template(page["content"], "Infobox Bonuses")
    if body is None:
        return (
            f"**{page['title']}** ({wiki_label} Wiki)\n"
            f"{page['url']}\n\n"
            f"No combat stats found — this item may not be combat equipment."
        )
    return _cache_and_return(
        _format_stats(page["title"], page["url"], wiki_label, _parse_fields(body), stats_def),
        cache_key,
    )


def _titles_match(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return (
        f'Did you mean **"{title}"** ({wiki_label} Wiki)?\n'
        f"{url}\n\n"
        f'Re-invoke `get_equipment_stats` with item_name="{title}" to fetch the stats.'
    )


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, _TTL)
    return value


# ---------------------------------------------------------------------------
# Wiki API helpers
# ---------------------------------------------------------------------------

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


async def _search_item(query: str, game: str) -> dict | None:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
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
    return {
        "title": title,
        "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
    }


# ---------------------------------------------------------------------------
# Wikitext parsing
# ---------------------------------------------------------------------------

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


def _clean(s: str) -> str:
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _format_stats(title: str, url: str, wiki_label: str, fields: dict, stats_def: list) -> str:
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]
    for label, key in stats_def:
        val = fields.get(key)
        if not val:
            continue
        cleaned = _clean(val)
        if cleaned:
            lines.append(f"**{label}:** {cleaned}")
    return "\n".join(lines)
