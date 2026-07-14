"""get_monster_info tool — RuneScape Wiki Infobox Monster (OSRS + RS3)."""

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import TTL_HOUR, WIKI_APIS, WIKI_LABELS
from ._http import http_get
from ._wiki_parsing import (
    clean_wikitext as _clean,
    disambiguate,
    fetch_page_params,
    find_template as _find_template,
    first_matching_page,
    parse_page_response,
    parse_template_fields as _parse_fields,
    search_params,
    titles_match as _titles_match,
)

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

    wiki_label = WIKI_LABELS[game]

    # Resolve via the first strategy that lands — the same chain achievements.py, equipment.py and
    # quests.py use. Monsters have no roman-numeral variants, so the chain is two links, not three.
    result = await _from_direct(monster_name, game, wiki_label) or await _from_search(
        monster_name, game, wiki_label
    )
    if result is None:
        return f"No monster found for '{monster_name}' on the {wiki_label} wiki."
    return _cache_and_return(result, cache_key)


def _format_page(page: dict, game: str, wiki_label: str) -> str:
    """Render a page already known to carry an Infobox Monster template."""
    body = _find_template(page["content"], "Infobox Monster")
    fields = _parse_fields(body)
    return _format_monster(page["title"], page["url"], wiki_label, fields, _FIELDS_BY_GAME[game])


async def _from_direct(monster_name: str, game: str, wiki_label: str) -> str | None:
    """Direct page lookup: format an exact hit, disambiguate a near-title, or — when the page exists
    but is not a monster — retry the '(monster)' and '(NPC)' disambiguation suffixes."""
    direct = await _fetch_page(monster_name, game, follow_redirects=True)
    if direct is None:
        return None

    if _find_template(direct["content"], "Infobox Monster") is not None:
        if _titles_match(monster_name, direct["title"]):
            return _format_page(direct, game, wiki_label)
        return _disambiguate(direct["title"], direct["url"], wiki_label)

    for suffix in ("monster", "NPC"):
        suffixed = await _fetch_page(f"{monster_name} ({suffix})", game, follow_redirects=True)
        if suffixed and _find_template(suffixed["content"], "Infobox Monster") is not None:
            return _format_page(suffixed, game, wiki_label)
    return None


async def _from_search(monster_name: str, game: str, wiki_label: str) -> str | None:
    candidate = await _search_monster(monster_name, game)
    if candidate is None:
        return None
    if not _titles_match(monster_name, candidate["title"]):
        return _disambiguate(candidate["title"], candidate["url"], wiki_label)
    # _search_monster guarantees candidate["content"] contains an Infobox Monster template.
    return _format_page(candidate, game, wiki_label)


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return disambiguate(title, url, wiki_label, "get_monster_info", "monster_name", "info")


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, TTL_HOUR)
    return value


# ---------------------------------------------------------------------------
# Wiki API helpers
# ---------------------------------------------------------------------------


async def _fetch_page(title: str, game: str, follow_redirects: bool) -> dict | None:
    data = await http_get(WIKI_APIS[game], params=fetch_page_params(title, follow_redirects))
    return parse_page_response(data, title, game)


async def _search_monster(query: str, game: str) -> dict | None:
    data = await http_get(WIKI_APIS[game], params=search_params(query))
    return first_matching_page(
        data, game, lambda c: _find_template(c, "Infobox Monster") is not None
    )


def _format_monster(
    title: str, url: str, wiki_label: str, fields: dict[str, str], fields_def: list[tuple[str, str]]
) -> str:
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]
    for label, key in fields_def:
        val = fields.get(key) or fields.get(f"{key}1")
        if not val:
            continue
        cleaned = _clean(val)
        if cleaned:
            lines.append(f"**{label}:** {cleaned}")
    return "\n".join(lines)
