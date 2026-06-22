"""Shared HTTP client utilities for RS MCP tools.

A single module-level AsyncClient is reused across calls so connections (and TLS
handshakes) are pooled instead of re-established per request. Transient failures —
network/transport errors and retryable status codes (429/502/503/504) — are retried
with a short linear backoff before the error is surfaced to the caller.
"""
import asyncio

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

# Short display label per game (used in result headers). Callers validate game
# against WIKI_APIS first, so a lookup here is always present.
WIKI_LABELS = {
    "rs3":  "RS3",
    "osrs": "OSRS",
}

MW_BASE_PARAMS = {
    "format": "json",
    "formatversion": 2,
}

# How many MediaWiki search candidates each typed tool fetches before type-filtering.
SEARCH_RESULT_LIMIT = 5

_MAX_RETRIES = 2
_RETRY_STATUSES = {429, 502, 503, 504}
_client: httpx.AsyncClient | None = None


def _ensure_client() -> httpx.AsyncClient:
    """Return the shared pooled client, recreating it if absent or closed."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(headers=HEADERS)
    return _client


async def _request(url: str, params: dict | None, timeout: float) -> httpx.Response:
    """GET with connection pooling and retry/backoff on transient failures."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await _ensure_client().get(url, params=params, timeout=timeout)
        except httpx.TransportError as exc:
            last_exc = exc
        else:
            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        if attempt < _MAX_RETRIES:
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_exc  # exhausted retries on transport errors


async def http_get(url: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    resp = await _request(url, params, timeout)
    return resp.json()


async def http_get_text(url: str, params: dict | None = None, timeout: float = 10.0) -> str:
    resp = await _request(url, params, timeout)
    return resp.text
