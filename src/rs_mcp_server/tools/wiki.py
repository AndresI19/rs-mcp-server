"""search_wiki tool — RuneScape Wiki MediaWiki API."""
from rs_mcp_server import cache
from rs_mcp_server.logging import instrument
from ._http import http_get, WIKI_APIS, WIKI_BASE_URLS, MW_BASE_PARAMS

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
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 1,
        "prop": "extracts|info",
        "exintro": True,
        "explaintext": True,
        "inprop": "url",
        **MW_BASE_PARAMS,
    }

    data = await http_get(WIKI_APIS[game], params=params)
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return f"No results found for '{query}' on the {wiki_label} wiki."

    page = pages[0]
    title = page.get("title", "Unknown")
    extract = (page.get("extract") or "").strip()
    url = f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}"

    if not extract:
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\nNo summary available."
    else:
        if len(extract) > _MAX_EXTRACT_CHARS:
            extract = extract[:_MAX_EXTRACT_CHARS].rsplit("\n", 1)[0] + "\n..."
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\n{extract}"

    cache.set(cache_key, result, _TTL)
    return result
