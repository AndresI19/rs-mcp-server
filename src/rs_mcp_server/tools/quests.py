"""get_quest_info tool — RuneScape Wiki quest data via MediaWiki API."""
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, WIKI_LABELS
from ._http import http_get
from ._wiki_parsing import (
    disambiguate,
    fetch_page_params,
    first_matching_page,
    parse_page_response,
    parse_template_fields as _parse_fields,
    render_variants,
    search_params,
    titles_match as _titles_match,
)

_TTL = 3600  # 1 hour — matches wiki lookup bucket

_TEMPLATES = ("Infobox Quest", "Quest details")

# (display label, keys to try in order) — a label falls back to its alternate keys,
# so "Quest series" takes `series` if present, else `main_series`.
_FIELDS = (
    ("Difficulty", ("difficulty",)),
    ("Length", ("length",)),
    ("Members", ("members",)),
    ("Quest series", ("series", "main_series")),
    ("Start point", ("start",)),
    ("Requirements", ("requirements",)),
    ("Items required", ("items",)),
    ("Recommended", ("recommended",)),
    ("Rewards", ("rewards",)),
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

    wiki_label = WIKI_LABELS[game]

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

    # Page exists but is the wrong type — try disambig suffix(es).
    if direct is not None:
        for suffix in ("quest",):
            suffixed = await _fetch_page(f"{quest_name} ({suffix})", game, follow_redirects=True)
            if suffixed and _has_quest_template(suffixed["content"]):
                return _cache_and_return(
                    _format_from_content(suffixed["title"], suffixed["url"], wiki_label, suffixed["content"]),
                    cache_key,
                )

    # Roman-numeral variant enumeration (#78).
    variants = await _enumerate_roman_variants(quest_name, game)
    if len(variants) == 1:
        v = variants[0]
        return _cache_and_return(
            _format_from_content(v["title"], v["url"], wiki_label, v["content"]),
            cache_key,
        )
    if len(variants) >= 2:
        return _cache_and_return(
            render_variants(variants, wiki_label, quest_name, "get_quest_info"),
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

    # _search_quest guarantees candidate["content"] contains a quest template.
    return _cache_and_return(
        _format_from_content(candidate["title"], candidate["url"], wiki_label, candidate["content"]),
        cache_key,
    )


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return disambiguate(title, url, wiki_label, "get_quest_info", "quest_name", "details")


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, _TTL)
    return value


# ---------------------------------------------------------------------------
# Wiki API helpers
# ---------------------------------------------------------------------------

async def _fetch_page(title: str, game: str, follow_redirects: bool) -> dict | None:
    """Direct title lookup. Returns dict with title/url/content, or None if missing."""
    data = await http_get(WIKI_APIS[game], params=fetch_page_params(title, follow_redirects))
    return parse_page_response(data, title, game)


async def _search_quest(query: str, game: str) -> dict | None:
    """Search restricted to quest pages via `incategory:Quests`. Falls back to plain search.

    Both tiers fetch top candidates with content and filter to pages whose wikitext
    contains a quest template — generic-named search hits (music tracks, NPCs sharing
    a quest's name) get skipped instead of confidently returned.
    """
    for search_term in (f'{query} incategory:"Quests"', query):
        data = await http_get(WIKI_APIS[game], params=search_params(search_term))
        match = first_matching_page(data, game, _has_quest_template)
        if match:
            return match
    return None


# ---------------------------------------------------------------------------
# Wikitext parsing
# ---------------------------------------------------------------------------

async def _enumerate_roman_variants(quest_name: str, game: str) -> list[dict]:
    """Try '<name> I' through '<name> V' in one batch query; return variants
    that exist and carry a quest template."""
    titles = "|".join(f"{quest_name} {n}" for n in ("I", "II", "III", "IV", "V"))
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
        if not _has_quest_template(content):
            continue
        title = page.get("title", "")
        found.append({
            "title": title,
            "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            "content": content,
        })
    return found


def _has_quest_template(wikitext: str) -> bool:
    return any(_find_template(wikitext, name) is not None for name in _TEMPLATES)


def _find_template(wikitext: str, name: str) -> str | None:
    """Walk balanced braces from `{{<name>` to its matching `}}`."""
    pattern = r"\{\{" + name.replace(" ", "[ _]") + r"(?=\s*[|}])"
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


def _merged_fields(wikitext: str) -> dict[str, str]:
    """Parse all known quest templates; later templates overwrite earlier ones."""
    merged: dict[str, str] = {}
    for name in _TEMPLATES:
        body = _find_template(wikitext, name)
        if body:
            merged.update(_parse_fields(body))
    return merged


def _first_value(fields: dict[str, str], keys: tuple[str, ...]) -> str:
    """First non-empty value among `keys`, letting a label fall back to an alternate key."""
    for k in keys:
        if fields.get(k):
            return fields[k]
    return ""


def _format_from_content(title: str, url: str, wiki_label: str, wikitext: str) -> str:
    fields = _merged_fields(wikitext)
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]
    for label, keys in _FIELDS:
        value = _first_value(fields, keys)
        if not value:
            continue
        cleaned = _clean_wikitext(value)
        if not cleaned:
            continue
        if "\n" in cleaned or len(cleaned) > 60:
            lines.append(f"**{label}:**")
            for sub in cleaned.split("\n"):
                if sub.strip():
                    lines.append(f"  {sub}")
        else:
            lines.append(f"**{label}:** {cleaned}")
    return "\n".join(lines)


def _clean_wikitext(s: str) -> str:
    s = re.sub(r"\{\{(?:Skillreq|SCP)\|([^|}]+)\|(\d+)[^}]*\}\}", r"Level \2 \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{plinkp?\|([^|}]+)[^}]*\}\}", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<br ?/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()
