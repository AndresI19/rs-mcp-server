"""search_wiki tool — RuneScape Wiki MediaWiki API."""
import httpx
import cache

_WIKI_API = "https://runescape.wiki/api.php"
_TTL = 3600  # 1 hour


async def search_wiki(query: str) -> str:
    cache_key = f"wiki:{query}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    raise NotImplementedError("search_wiki not yet implemented")
