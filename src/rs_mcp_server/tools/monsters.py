"""get_monster_info tool — RuneScape Wiki Infobox Monster (OSRS + RS3)."""

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, SEARCH_RESULT_LIMIT, WIKI_APIS, WIKI_BASE_URLS, http_get
from ._wiki_parsing import (
    clean_wikitext as _clean,
    find_template as _find_template,
    parse_template_fields as _parse_fields,
    titles_match as _titles_match,
)

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

        # Page exists but is the wrong type — try disambig suffix(es).
        for suffix in ("monster", "NPC"):
            suffixed = await _fetch_page(f"{monster_name} ({suffix})", game, follow_redirects=True)
            if suffixed is not None:
                body = _find_template(suffixed["content"], "Infobox Monster")
                if body is not None:
                    return _cache_and_return(
                        _format_monster(suffixed["title"], suffixed["url"], wiki_label, _parse_fields(body), fields_def),
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

    # _search_monster guarantees candidate["content"] contains an Infobox Monster template.
    body = _find_template(candidate["content"], "Infobox Monster")
    return _cache_and_return(
        _format_monster(candidate["title"], candidate["url"], wiki_label, _parse_fields(body), fields_def),
        cache_key,
    )


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
        "gsrlimit": SEARCH_RESULT_LIMIT,
        "prop": "revisions|info",
        "rvprop": "content",
        "rvslots": "main",
        "inprop": "url",
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS[game], params=params)
    for page in data.get("query", {}).get("pages", []):
        revisions = page.get("revisions") or []
        if not revisions:
            continue
        content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
        if _find_template(content, "Infobox Monster") is None:
            continue
        title = page.get("title", "")
        return {
            "title": title,
            "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            "content": content,
        }
    return None


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
