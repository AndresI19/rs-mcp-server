"""get_monster_info tool — RuneScape Wiki Infobox Monster (OSRS + RS3)."""
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get

_TTL = 3600

_OSRS_FIELDS = [
    ("Combat level", "combat"),
    ("Hitpoints", "hitpoints"),
    ("Max hit", "max hit"),
    ("Attack style", "attack style"),
    ("Attack speed", "attack speed"),
    ("Aggressive", "aggressive"),
    ("Poisonous", "poisonous"),
    ("Attributes", "attributes"),
    ("Slayer level", "slaylvl"),
    ("Slayer XP", "slayxp"),
    ("Slayer category", "cat"),
    ("Assigned by", "assignedby"),
    ("Members", "members"),
    ("Examine", "examine"),
]

_RS3_FIELDS = [
    ("Combat level", "level"),
    ("Life points", "lifepoints"),
    ("Combat XP", "experience"),
    ("Style", "style"),
    ("Primary style", "primarystyle"),
    ("Attack speed", "speed"),
    ("Aggressive", "aggressive"),
    ("Poisonous", "poisonous"),
    ("Slayer level", "slaylvl"),
    ("Slayer XP", "slayxp"),
    ("Slayer category", "slayercat"),
    ("Assigned by", "assigned_by"),
    ("Weakness", "weakness"),
    ("Susceptibility", "susceptibility"),
    ("Armour", "armour"),
    ("Defence", "defence"),
    ("Members", "members"),
    ("Examine", "examine"),
]

_FIELDS_BY_GAME = {"osrs": _OSRS_FIELDS, "rs3": _RS3_FIELDS}


@instrument("get_monster_info")
async def get_monster_info(monster_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not monster_name.strip():
        return "No monster name provided."

    cache_key = f"monsters:{game}:{monster_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = "RS3" if game == "rs3" else "OSRS"
    fields_def = _FIELDS_BY_GAME[game]

    direct = await _fetch_page(monster_name, game, follow_redirects=True)
    if direct is not None:
        body = _find_template(direct["content"], "Infobox Monster")
        if body is not None:
            if _titles_match(monster_name, direct["title"]):
                return _cache_and_return(
                    _format_monster(direct["title"], direct["url"], wiki_label, _parse_fields(body), fields_def),
                    cache_key,
                )
            return _cache_and_return(
                _disambiguate(direct["title"], direct["url"], wiki_label),
                cache_key,
            )

    candidate = await _search_monster(monster_name, game)
    if candidate is None:
        return f"No monster found for '{monster_name}' on the {wiki_label} wiki."

    if not _titles_match(monster_name, candidate["title"]):
        return _cache_and_return(
            _disambiguate(candidate["title"], candidate["url"], wiki_label),
            cache_key,
        )

    page = await _fetch_page(candidate["title"], game, follow_redirects=False)
    if page is None:
        return f"No monster found for '{monster_name}' on the {wiki_label} wiki."
    body = _find_template(page["content"], "Infobox Monster")
    if body is None:
        return (
            f"**{page['title']}** ({wiki_label} Wiki)\n"
            f"{page['url']}\n\n"
            f"No monster info found — this page may not be a monster article."
        )
    return _cache_and_return(
        _format_monster(page["title"], page["url"], wiki_label, _parse_fields(body), fields_def),
        cache_key,
    )


def _titles_match(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return (
        f'Did you mean **"{title}"** ({wiki_label} Wiki)?\n'
        f"{url}\n\n"
        f'Re-invoke `get_monster_info` with monster_name="{title}" to fetch the info.'
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


async def _search_monster(query: str, game: str) -> dict | None:
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


def _format_monster(title: str, url: str, wiki_label: str, fields: dict, fields_def: list) -> str:
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]
    for label, key in fields_def:
        val = fields.get(key) or fields.get(f"{key}1")
        if not val:
            continue
        cleaned = _clean(val)
        if cleaned:
            lines.append(f"**{label}:** {cleaned}")
    return "\n".join(lines)
