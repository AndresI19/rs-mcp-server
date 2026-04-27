"""search_wiki tool — RuneScape Wiki MediaWiki API."""
import httpx
import cache

_WIKI_APIS = {
    "rs3": "https://runescape.wiki/api.php",
    "osrs": "https://oldschool.runescape.wiki/api.php",
}
_WIKI_BASE_URLS = {
    "rs3": "https://runescape.wiki/w/",
    "osrs": "https://oldschool.runescape.wiki/w/",
}
_TTL = 3600  # 1 hour
_MAX_EXTRACT_CHARS = 1500


async def search_wiki(query: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in _WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

    cache_key = f"wiki:{game}:{query}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    api_url = _WIKI_APIS[game]
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
        "format": "json",
        "formatversion": 2,
    }

    async with httpx.AsyncClient(headers={"User-Agent": "RS-MCP-Server/1.0"}) as client:
        resp = await client.get(api_url, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return f"No results found for '{query}' on the {wiki_label} wiki."

    page = pages[0]
    title = page.get("title", "Unknown")
    extract = (page.get("extract") or "").strip()
    url = f"{_WIKI_BASE_URLS[game]}{title.replace(' ', '_')}"

    if not extract:
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\nNo summary available."
    else:
        if len(extract) > _MAX_EXTRACT_CHARS:
            extract = extract[:_MAX_EXTRACT_CHARS].rsplit("\n", 1)[0] + "\n..."
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\n{extract}"

    cache.set(cache_key, result, _TTL)
    return result
