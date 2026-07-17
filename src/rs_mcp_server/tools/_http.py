"""Shared HTTP client utilities for RS MCP tools.

A single module-level AsyncClient is reused across calls so connections (and TLS
handshakes) are pooled instead of re-established per request. Transient failures —
network/transport errors and retryable status codes (429/502/503/504) — are retried
with a short linear backoff before the error is surfaced to the caller.
"""

import asyncio

import httpx

from rs_mcp_server.config import HTTP_MAX_RETRIES, HTTP_TIMEOUT, USER_AGENT

# The wikis ask that tools identify themselves; USER_AGENT is overridable (see config.py).
HEADERS = {"User-Agent": USER_AGENT}


class RetryingClient:
    """A pooled httpx.AsyncClient that retries transient failures (see module docstring)."""

    def __init__(
        self,
        headers: dict[str, str],
        max_retries: int = HTTP_MAX_RETRIES,
        retry_statuses: frozenset[int] = frozenset({429, 502, 503, 504}),
    ) -> None:
        self._headers = headers
        self._max_retries = max_retries
        self._retry_statuses = retry_statuses
        self._client: httpx.AsyncClient | None = None

    def _ensure(self) -> httpx.AsyncClient:
        """Return the pooled client, recreating it if absent or closed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(headers=self._headers)
        return self._client

    async def request(self, url: str, params: dict | None, timeout: float) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._ensure().get(url, params=params, timeout=timeout)
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code in self._retry_statuses and attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            if attempt < self._max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
        raise last_exc  # exhausted retries on transport errors


_CLIENT = RetryingClient(HEADERS)


async def http_get(url: str, params: dict | None = None, timeout: float = HTTP_TIMEOUT) -> dict:
    """GET JSON via the shared retrying client."""
    resp = await _CLIENT.request(url, params, timeout)
    return resp.json()


async def http_get_text(url: str, params: dict | None = None, timeout: float = HTTP_TIMEOUT) -> str:
    """GET text via the shared retrying client. Honours HTTP_TIMEOUT like http_get (must stay
    config-driven; a hardcoded default silently ignores a tightened config timeout)."""
    resp = await _CLIENT.request(url, params, timeout)
    return resp.text
