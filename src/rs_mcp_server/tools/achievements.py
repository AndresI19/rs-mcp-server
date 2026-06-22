"""get_achievement tool — RuneScape Wiki achievement infoboxes (OSRS + RS3)."""

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
    ("Infobox Achievement Diary",  _OSRS_DIARY_FIELDS, "Achievement Diary"),
    ("Infobox Achievement",        _RS3_FIELDS,        "Achievement"),
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

    wiki_label = "RS3" if game == "rs3" else "OSRS"

    direct = await _fetch_page(name, game, follow_redirects=True)
    if direct is not None:
        match = _dispatch(direct["content"])
        if match is not None:
            body, fields_def, kind = match
            if _titles_match(name, direct["title"]):
                return _cache_and_return(
                    _format_achievement(direct["title"], direct["url"], wiki_label, kind, _parse_fields(body), fields_def),
                    cache_key,
                )
            return _cache_and_return(
                _disambiguate(direct["title"], direct["url"], wiki_label),
                cache_key,
            )

        # Page exists but is the wrong type (e.g. Flow_State is a relic page,
        # but Flow_State_(achievement) exists). Retry with disambig suffix.
        for suffix in ("achievement",):
            suffixed = await _fetch_page(f"{name} ({suffix})", game, follow_redirects=True)
            if suffixed is not None:
                match = _dispatch(suffixed["content"])
                if match is not None:
                    body, fields_def, kind = match
                    return _cache_and_return(
                        _format_achievement(suffixed["title"], suffixed["url"], wiki_label, kind, _parse_fields(body), fields_def),
                        cache_key,
                    )

    # Roman-numeral variant enumeration (#78): handles names like "Are You
    # Winning, Zam?" where the bare page isn't an achievement but I/II/III/IV
    # variants are. One batch query covers all five suffixes.
    variants = await _enumerate_roman_variants(name, game)
    if len(variants) == 1:
        v = variants[0]
        body, fields_def, kind = _dispatch(v["content"])
        return _cache_and_return(
            _format_achievement(v["title"], v["url"], wiki_label, kind, _parse_fields(body), fields_def),
            cache_key,
        )
    if len(variants) >= 2:
        return _cache_and_return(
            _render_variants(variants, wiki_label, name),
            cache_key,
        )

    candidate = await _search_achievement(name, game)
    if candidate is None:
        return f"No achievement found for '{name}' on the {wiki_label} wiki."

    if not _titles_match(name, candidate["title"]):
        return _cache_and_return(
            _disambiguate(candidate["title"], candidate["url"], wiki_label),
            cache_key,
        )

    # _search_achievement guarantees candidate["content"] contains an achievement template.
    body, fields_def, kind = _dispatch(candidate["content"])
    return _cache_and_return(
        _format_achievement(candidate["title"], candidate["url"], wiki_label, kind, _parse_fields(body), fields_def),
        cache_key,
    )


def _dispatch(content: str) -> tuple[str, list, str] | None:
    for template_name, fields_def, kind in _TEMPLATE_DISPATCH:
        body = _find_template(content, template_name)
        if body is not None:
            return body, fields_def, kind
    return None


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return (
        f'Did you mean **"{title}"** ({wiki_label} Wiki)?\n'
        f"{url}\n\n"
        f'Re-invoke `get_achievement` with name="{title}" to fetch the info.'
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


async def _search_achievement(query: str, game: str) -> dict | None:
    # Fetch top candidates with content so we can type-filter: skip pages
    # that don't carry one of the achievement infobox templates.
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
        if _dispatch(content) is None:
            continue
        title = page.get("title", "")
        return {
            "title": title,
            "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            "content": content,
        }
    return None


async def _enumerate_roman_variants(name: str, game: str) -> list[dict]:
    """Try '<name> I' through '<name> V' in one batch query; return variants
    that exist and carry an achievement template."""
    titles = "|".join(f"{name} {n}" for n in ("I", "II", "III", "IV", "V"))
    params = {
        "action": "query",
        "titles": titles,
        "prop": "revisions|info",
        "rvprop": "content",
        "rvslots": "main",
        "inprop": "url",
        "redirects": 1,
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS[game], params=params)
    found: list[dict] = []
    for page in data.get("query", {}).get("pages", []):
        if page.get("missing"):
            continue
        revisions = page.get("revisions") or []
        if not revisions:
            continue
        content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
        if _dispatch(content) is None:
            continue
        title = page.get("title", "")
        found.append({
            "title": title,
            "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            "content": content,
        })
    return found


def _render_variants(variants: list[dict], wiki_label: str, base_name: str) -> str:
    lines = [f'Multiple tiered variants of **"{base_name}"** found ({wiki_label} Wiki):', ""]
    for v in variants:
        lines.append(f"- **{v['title']}** — {v['url']}")
    lines.append("")
    lines.append("Re-invoke `get_achievement` with the exact tier name to fetch full details.")
    return "\n".join(lines)


def _format_achievement(title: str, url: str, wiki_label: str, kind: str, fields: dict, fields_def: list) -> str:
    lines = [f"**{title}** — {kind} ({wiki_label} Wiki)", url, ""]
    for label, key in fields_def:
        val = fields.get(key) or fields.get(f"{key}1")
        if not val:
            continue
        cleaned = _clean(val)
        if cleaned:
            lines.append(f"**{label}:** {cleaned}")
    return "\n".join(lines)
