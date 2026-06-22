"""search_wiki tool — RuneScape Wiki MediaWiki API.

Two-step flow: search for the matching page title via action=query, then fetch
the rendered HTML body via action=parse so transcluded templates (set bonuses,
passive effects, etc.) appear in results. Falls back to alias-substituted
queries (gauntlets→melee gloves, helm→helmet) when the initial search misses.
"""
import html
import re

import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._aliases import expand_aliases
from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get

_TTL = 3600  # 1 hour
_MAX_EXTRACT_CHARS = 1500


@instrument("search_wiki")
async def search_wiki(query: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

    cache_key = f"wiki:{game}:{query}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = "RS3" if game == "rs3" else "OSRS"

    title = await _find_title(query, game)
    if title is None:
        for alt in expand_aliases(query)[1:]:
            title = await _find_title(alt, game)
            if title is not None:
                break

    if title is None:
        return f"No results found for '{query}' on the {wiki_label} wiki."

    body = await _fetch_rendered_body(title, game)
    url = f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}"

    if not body:
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\nNo summary available."
    else:
        if len(body) > _MAX_EXTRACT_CHARS:
            body = body[:_MAX_EXTRACT_CHARS].rsplit("\n", 1)[0] + "\n..."
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\n{body}"

    cache.set(cache_key, result, _TTL)
    return result


async def _find_title(query: str, game: str) -> str | None:
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
    title = pages[0].get("title") or None
    return title


async def _fetch_rendered_body(title: str, game: str) -> str:
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "disableeditsection": 1,
        "redirects": 1,
        **MW_BASE_PARAMS,
    }
    try:
        data = await http_get(WIKI_APIS[game], params=params)
    except httpx.HTTPError:
        return ""
    if "error" in data:
        return ""
    html_text = data.get("parse", {}).get("text") or ""
    return _extract_prose_from_html(html_text)


def _extract_prose_from_html(html_text: str) -> str:
    """Extract section headings + paragraph prose from rendered HTML, skipping chrome.

    Pulls text from <h2>/<h3> and <p> tags only, preserving page order. Drops
    infoboxes (<table>), navboxes/hatnotes (<div>), and other UI elements.
    Set-bonus and passive-effect templates render to <p>, so this captures them;
    the section headers stay so the reader sees the structure (== Set bonus ==
    followed by its prose body, never one without the other).
    """
    pieces: list[str] = []
    for match in re.finditer(r"<(h2|h3|p)\b[^>]*>(.*?)</\1>", html_text, re.DOTALL):
        tag, raw = match.group(1), match.group(2)
        text = re.sub(r"<[^>]+>", " ", raw)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if tag == "h2":
            pieces.append(f"\n## {text}")
        elif tag == "h3":
            pieces.append(f"\n### {text}")
        else:
            pieces.append(text)
    return "\n".join(pieces).strip()
