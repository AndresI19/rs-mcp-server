"""Shared HTTP client utilities for RS MCP tools."""
import httpx

HEADERS = {"User-Agent": "RS-MCP-Server/1.0"}

WIKI_APIS = {
    "rs3":  "https://runescape.wiki/api.php",
    "osrs": "https://oldschool.runescape.wiki/api.php",
}

WIKI_BASE_URLS = {
    "rs3":  "https://runescape.wiki/w/",
    "osrs": "https://oldschool.runescape.wiki/w/",
}

MW_BASE_PARAMS = {
    "format": "json",
    "formatversion": 2,
}


async def http_get(url: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    async with httpx.AsyncClient(headers=HEADERS) as client:
        resp = await client.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
