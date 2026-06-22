"""get_equipment_stats tool — RuneScape Wiki Infobox Bonuses (OSRS + RS3)."""
import html
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get
from ._wiki_parsing import (
    clean_wikitext as _clean,
    find_template as _find_template,
    parse_template_fields as _parse_fields,
    titles_match as _titles_match,
)

_TTL = 3600

# Section headings whose prose should be surfaced alongside the infobox.
# Each entry is (canonical display label, accepted heading variants — lowercased).
_SECTION_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Set bonus",          ("set bonus", "set effect", "set effects")),
    ("Passive",            ("passive", "passive effect", "passive effects", "passive ability")),
    ("Special attack",     ("special attack", "special attacks")),
    ("Special properties", ("special properties", "special property", "properties")),
)

_SECTION_PROSE_LIMIT = 400

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
    ("Armour", "armour"),
    ("Life points", "life"),
    ("Prayer", "prayer"),
    ("Magic damage", "magic"),
    ("Ranged damage", "ranged"),
    ("Strength", "strength"),
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
                sections = await _fetch_named_sections(direct["title"], game)
                return _cache_and_return(
                    _format_stats(direct["title"], direct["url"], wiki_label, _parse_fields(body), stats_def, sections),
                    cache_key,
                )
            return _cache_and_return(
                _disambiguate(direct["title"], direct["url"], wiki_label),
                cache_key,
            )

    candidate = await _search_equipment(item_name, game)
    if candidate is None:
        return f"No equipment found for '{item_name}' on the {wiki_label} wiki."

    if not _titles_match(item_name, candidate["title"]):
        return _cache_and_return(
            _disambiguate(candidate["title"], candidate["url"], wiki_label),
            cache_key,
        )

    # _search_equipment guarantees candidate["content"] contains an Infobox Bonuses template.
    body = _find_template(candidate["content"], "Infobox Bonuses")
    sections = await _fetch_named_sections(candidate["title"], game)
    return _cache_and_return(
        _format_stats(candidate["title"], candidate["url"], wiki_label, _parse_fields(body), stats_def, sections),
        cache_key,
    )


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


async def _search_equipment(query: str, game: str) -> dict | None:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 5,
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
        if _find_template(content, "Infobox Bonuses") is None:
            continue
        title = page.get("title", "")
        return {
            "title": title,
            "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            "content": content,
        }
    return None




def _format_stats(title: str, url: str, wiki_label: str, fields: dict, stats_def: list, sections: dict[str, str]) -> str:
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]
    for label, key in stats_def:
        val = fields.get(key)
        if not val:
            continue
        cleaned = _clean(val)
        if cleaned:
            lines.append(f"**{label}:** {cleaned}")

    for label, _aliases in _SECTION_TARGETS:
        prose = sections.get(label)
        if prose:
            lines.append("")
            lines.append(f"## {label}")
            lines.append(prose)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Named-section prose enrichment (issue #77)
# ---------------------------------------------------------------------------

async def _fetch_named_sections(title: str, game: str) -> dict[str, str]:
    """Fetch the rendered page and extract prose for the target named sections.

    Returns {} on any error — set-bonus prose is enrichment, not core data.
    """
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "redirects": 1,
        **MW_BASE_PARAMS,
    }
    try:
        data = await http_get(WIKI_APIS[game], params=params)
    except Exception:
        return {}
    if "error" in data:
        return {}
    html_text = data.get("parse", {}).get("text") or ""
    return _extract_named_sections(html_text)


def _extract_named_sections(html_text: str) -> dict[str, str]:
    """Slice the rendered HTML on <h2> boundaries; pull prose from sections we recognise."""
    chunks = re.split(r"(<h2\b[^>]*>.*?</h2>)", html_text, flags=re.DOTALL)
    # chunks alternates: [body_before_first_h2, h2, body, h2, body, ...]
    sections: dict[str, str] = {}
    for i in range(1, len(chunks), 2):
        heading_html = chunks[i]
        body_html = chunks[i + 1] if i + 1 < len(chunks) else ""
        heading_text = re.sub(r"<[^>]+>", "", heading_html).strip().lower()
        for label, aliases in _SECTION_TARGETS:
            if heading_text in aliases and label not in sections:
                prose = _extract_paragraphs(body_html)
                if prose:
                    sections[label] = _truncate(prose, _SECTION_PROSE_LIMIT)
                break
    return sections


def _extract_paragraphs(html_text: str) -> str:
    paragraphs: list[str] = []
    for raw in re.findall(r"<p\b[^>]*>(.*?)</p>", html_text, re.DOTALL):
        text = re.sub(r"<[^>]+>", " ", raw)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(".", 1)[0]
    return (cut + "." if cut else s[:limit]) + " …"
