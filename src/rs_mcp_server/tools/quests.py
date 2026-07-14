"""get_quest_info tool — RuneScape Wiki quest data via MediaWiki API."""

import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import *
from ._http import http_get
from ._wiki_parsing import (
    disambiguate,
    fetch_page_params,
    first_matching_page,
    parse_page_response,
    parse_template_fields as _parse_fields,
    render_variants,
    roman_variant_titles,
    search_params,
    titles_match as _titles_match,
)

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

    # Resolve via the first strategy that lands — the same chain achievements.py, equipment.py and
    # moneymakers.py already use. Previously this was the cascade written out inline, which meant
    # _cache_and_return(...) appeared at six separate exit points and the shape of the search was
    # buried in the plumbing.
    result = (
        await _from_direct(quest_name, game, wiki_label)
        or await _from_roman_variants(quest_name, game, wiki_label)
        or await _from_search(quest_name, game, wiki_label)
    )
    if result is None:
        return f"No quest found for '{quest_name}' on the {wiki_label} wiki."
    return _cache_and_return(result, cache_key)


def _format_page(page: dict, wiki_label: str) -> str:
    return _format_from_content(page["title"], page["url"], wiki_label, page["content"])


async def _from_direct(quest_name: str, game: str, wiki_label: str) -> str | None:
    """Direct page lookup: format an exact hit, disambiguate a near-title, or — when the page exists
    but is not a quest (a music track or NPC sharing the name) — retry the '(quest)' suffix."""
    direct = await _fetch_page(quest_name, game, follow_redirects=True)
    if direct is None:
        return None

    if _has_quest_template(direct["content"]):
        if _titles_match(quest_name, direct["title"]):
            return _format_page(direct, wiki_label)
        return _disambiguate(direct["title"], direct["url"], wiki_label)

    for suffix in ("quest",):
        suffixed = await _fetch_page(f"{quest_name} ({suffix})", game, follow_redirects=True)
        if suffixed and _has_quest_template(suffixed["content"]):
            return _format_page(suffixed, wiki_label)
    return None


async def _from_roman_variants(quest_name: str, game: str, wiki_label: str) -> str | None:
    """Roman-numeral variant enumeration (#78): one variant formats, several disambiguate."""
    variants = await _enumerate_roman_variants(quest_name, game)
    if len(variants) == 1:
        return _format_page(variants[0], wiki_label)
    if len(variants) >= 2:
        return render_variants(variants, wiki_label, quest_name, "get_quest_info")
    return None


async def _from_search(quest_name: str, game: str, wiki_label: str) -> str | None:
    candidate = await _search_quest(quest_name, game)
    if candidate is None:
        return None
    if not _titles_match(quest_name, candidate["title"]):
        return _disambiguate(candidate["title"], candidate["url"], wiki_label)
    # _search_quest guarantees candidate["content"] contains a quest template.
    return _format_page(candidate, wiki_label)


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return disambiguate(title, url, wiki_label, "get_quest_info", "quest_name", "details")


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, TTL_HOUR)
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
    titles = roman_variant_titles(quest_name)
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
        found.append(
            {
                "title": title,
                "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
                "content": content,
            }
        )
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
        if wikitext[i : i + 2] == "{{":
            depth += 2
            i += 2
        elif wikitext[i : i + 2] == "}}":
            depth -= 2
            i += 2
        else:
            i += 1
    if depth != 0:
        return None
    return wikitext[match.end() : i - 2]


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
    s = re.sub(
        r"\{\{(?:Skillreq|SCP)\|([^|}]+)\|(\d+)[^}]*\}\}", r"Level \2 \1", s, flags=re.IGNORECASE
    )
    s = re.sub(r"\{\{plinkp?\|([^|}]+)[^}]*\}\}", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<br ?/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()
