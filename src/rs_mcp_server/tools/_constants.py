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
