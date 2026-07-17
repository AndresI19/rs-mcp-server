"""Static configuration constants shared across the RS MCP tools.

Kept apart from _http (which owns the HTTP client) so wiki/API config isn't coupled to transport.
Endpoints are re-exported from rs_mcp_server.config so every tool's `from ._constants import *`
keeps working, but config is the single place an endpoint is actually *set* — not this file.
"""

from rs_mcp_server.config import (  # noqa: F401  (re-exported for the tools)
    OSRS_PRICES_BASE,
    WIKI_APIS,
    WIKI_BASE_URLS,
)

# Short display label per game (result headers). Callers validate game against WIKI_APIS
# first, so a lookup here is always present.
WIKI_LABELS = {
    "rs3": "RS3",
    "osrs": "OSRS",
}

MW_BASE_PARAMS = {
    "format": "json",
    "formatversion": 2,
}

# How many MediaWiki search candidates each typed tool fetches before type-filtering.
SEARCH_RESULT_LIMIT = 5

# Cache TTLs in seconds. Wiki lookups bucket at one hour; live OSRS prices refresh
# every ~5 minutes; the GE item mapping changes only on updates.
TTL_5MIN = 300
TTL_10MIN = 600
TTL_HOUR = 3600
TTL_DAY = 86400

# OSRS real-time prices API, shared by the price and alchables tools. Base from config; the
# endpoints hang off it so the host/version is single-sourced.
OSRS_PRICES_MAPPING = f"{OSRS_PRICES_BASE}/mapping"
OSRS_PRICES_LATEST = f"{OSRS_PRICES_BASE}/latest"
OSRS_PRICES_1H = f"{OSRS_PRICES_BASE}/1h"
OSRS_PRICES_5M = f"{OSRS_PRICES_BASE}/5m"
