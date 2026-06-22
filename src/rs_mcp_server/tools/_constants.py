"""Static configuration constants shared across the RS MCP tools.

Pure data only — no logic and no imports. Kept apart from _http (which owns the
HTTP client) so the wiki/API configuration isn't coupled to the transport layer.
"""

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

# Cache TTLs in seconds. Wiki lookups bucket at one hour; the live OSRS price
# endpoints refresh every ~5 minutes; the GE item mapping changes only on updates.
TTL_5MIN = 300
TTL_10MIN = 600
TTL_HOUR = 3600
TTL_DAY = 86400

# OSRS real-time prices API (prices.runescape.wiki), shared by the price and
# alchables tools.
OSRS_PRICES_MAPPING = "https://prices.runescape.wiki/api/v1/osrs/mapping"
OSRS_PRICES_LATEST = "https://prices.runescape.wiki/api/v1/osrs/latest"
OSRS_PRICES_1H = "https://prices.runescape.wiki/api/v1/osrs/1h"
OSRS_PRICES_5M = "https://prices.runescape.wiki/api/v1/osrs/5m"
