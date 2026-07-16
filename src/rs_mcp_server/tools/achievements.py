"""get_achievement tool — RuneScape Wiki achievement infoboxes (OSRS + RS3)."""

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import *
from ._http import http_get
from ._registry import ToolSpec, game_param, object_schema, register
from ._wiki_parsing import (
    clean_wikitext as _clean,
    disambiguate,
    fetch_page_params,
    find_template as _find_template,
    first_matching_page,
    matching_pages,
    parse_page_response,
    parse_template_fields as _parse_fields,
    render_labeled_fields,
    render_variants,
    roman_variant_params,
    roman_variant_titles,
    search_params,
    titles_match as _titles_match,
)

_OSRS_CA_FIELDS = [
    ("Description", "description"),
    ("Tier", "tier"),
    ("Type", "type"),
    ("Monster", "monster"),
    ("Members", "members"),
    ("League region", "leagueregion"),
    ("Release", "release"),
]

_OSRS_DIARY_FIELDS = [
    ("Areas", "areas"),
    ("Members", "members"),
    ("Taskmasters", "taskmasters"),
    ("Reward", "reward"),
    ("League region", "leagueregion"),
    ("Release", "release"),
]

_RS3_FIELDS = [
    ("Description", "description"),
    ("Score", "score"),
    ("Main category", "maincategory"),
    ("Subcategory", "subcategory"),
    ("Requirements", "requirements"),
    ("Members", "members"),
    ("Release", "release"),
]

_TEMPLATE_DISPATCH = [
    ("Infobox Combat Achievement", _OSRS_CA_FIELDS, "Combat Achievement"),
    ("Infobox Achievement Diary", _OSRS_DIARY_FIELDS, "Achievement Diary"),
    ("Infobox Achievement", _RS3_FIELDS, "Achievement"),
]


@instrument("get_achievement")
async def get_achievement(name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not name.strip():
        return "No achievement name provided."

    cache_key = f"achievements:{game}:{name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = WIKI_LABELS[game]

    # Resolve via the first strategy that lands: an exact/disambiguating direct hit,
    # a tiered roman-numeral variant set, then a type-filtered search.
    result = (
        await _from_direct(name, game, wiki_label)
        or await _from_roman_variants(name, game, wiki_label)
        or await _from_search(name, game, wiki_label)
    )
    if result is None:
        return f"No achievement found for '{name}' on the {wiki_label} wiki."
    return _cache_and_return(result, cache_key)


def _format_match(title: str, url: str, wiki_label: str, match: tuple) -> str:
    """Render an achievement from a _dispatch() match — (body, fields_def, kind)."""
    body, fields_def, kind = match
    return _format_achievement(title, url, wiki_label, kind, _parse_fields(body), fields_def)


async def _from_direct(name: str, game: str, wiki_label: str) -> str | None:
    """Direct page lookup: format an exact hit, disambiguate a near-title, or — when
    the page exists but is the wrong type — retry an '(achievement)' disambig suffix."""
    direct = await _fetch_page(name, game, follow_redirects=True)
    if direct is None:
        return None
    match = _dispatch(direct["content"])
    if match is not None:
        if _titles_match(name, direct["title"]):
            return _format_match(direct["title"], direct["url"], wiki_label, match)
        return _disambiguate(direct["title"], direct["url"], wiki_label)

    # Page exists but is the wrong type (e.g. Flow_State is a relic page, but
    # Flow_State_(achievement) exists). Retry with a disambig suffix.
    for suffix in ("achievement",):
        suffixed = await _fetch_page(f"{name} ({suffix})", game, follow_redirects=True)
        if suffixed is not None:
            match = _dispatch(suffixed["content"])
            if match is not None:
                return _format_match(suffixed["title"], suffixed["url"], wiki_label, match)
    return None


async def _from_roman_variants(name: str, game: str, wiki_label: str) -> str | None:
    """Roman-numeral variant enumeration (#78): handles names like 'Are You Winning,
    Zam?' whose bare page isn't an achievement but whose I–V variants are."""
    variants = await _enumerate_roman_variants(name, game)
    if len(variants) == 1:
        v = variants[0]
        return _format_match(v["title"], v["url"], wiki_label, _dispatch(v["content"]))
    if len(variants) >= 2:
        return render_variants(variants, wiki_label, name, "get_achievement")
    return None


async def _from_search(name: str, game: str, wiki_label: str) -> str | None:
    """Type-filtered search fallback: disambiguate a near-title, else format the hit."""
    candidate = await _search_achievement(name, game)
    if candidate is None:
        return None
    if not _titles_match(name, candidate["title"]):
        return _disambiguate(candidate["title"], candidate["url"], wiki_label)
    return _format_match(
        candidate["title"], candidate["url"], wiki_label, _dispatch(candidate["content"])
    )


def _dispatch(content: str) -> tuple[str, list[tuple[str, str]], str] | None:
    for template_name, fields_def, kind in _TEMPLATE_DISPATCH:
        body = _find_template(content, template_name)
        if body is not None:
            return body, fields_def, kind
    return None


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return disambiguate(title, url, wiki_label, "get_achievement", "name", "info")


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, TTL_HOUR)
    return value


# ---------------------------------------------------------------------------
# Wiki API helpers
# ---------------------------------------------------------------------------


async def _fetch_page(title: str, game: str, follow_redirects: bool) -> dict | None:
    data = await http_get(WIKI_APIS[game], params=fetch_page_params(title, follow_redirects))
    return parse_page_response(data, title, game)


async def _search_achievement(query: str, game: str) -> dict | None:
    # Fetch top candidates with content so we can type-filter: skip pages
    # that don't carry one of the achievement infobox templates.
    data = await http_get(WIKI_APIS[game], params=search_params(query))
    return first_matching_page(data, game, lambda c: _dispatch(c) is not None)


async def _enumerate_roman_variants(name: str, game: str) -> list[dict]:
    """Try '<name> I' through '<name> V' in one batch query; return variants
    that exist and carry an achievement template."""
    titles = roman_variant_titles(name)
    data = await http_get(WIKI_APIS[game], params=roman_variant_params(titles))
    return matching_pages(data, game, lambda c: _dispatch(c) is not None)


def _format_achievement(
    title: str,
    url: str,
    wiki_label: str,
    kind: str,
    fields: dict[str, str],
    fields_def: list[tuple[str, str]],
) -> str:
    lines = [f"**{title}** — {kind} ({wiki_label} Wiki)", url, ""]
    lines += render_labeled_fields(fields, fields_def, _clean, numbered_fallback=True)
    return "\n".join(lines)


TOOL = register(
    ToolSpec(
        name="get_achievement",
        description="Look up a RuneScape achievement on the wiki — works for OSRS Combat Achievements (per-task), OSRS Achievement Diaries (summary only), and RS3 achievements (per-task). Returns description, tier or category, requirements, and rewards. For per-player completion progress, use get_player_achievement_progress.",
        input_schema=object_schema(
            {
                "name": {
                    "type": "string",
                    "description": "The achievement name (e.g. 'Noxious Foe', 'Falador Diary', 'The Essence of Magic').",
                },
                "game": game_param(
                    "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                ),
            },
            required=["name"],
        ),
        invoke=lambda args: get_achievement(args["name"], args.get("game", "rs3")),
    )
)
