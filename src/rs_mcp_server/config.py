"""The server's entire configuration surface, resolved from the environment and validated on import.

Everything here has a working default: the server runs with an empty environment. What it does NOT
do any more is *bake in* the answers. Before this module the listen address existed only inside
`if __name__ == "__main__"`, the HTTP timeout was a default argument on one function, the User-Agent
was a literal, and every upstream endpoint was a constant — so running against a mirror, tightening a
timeout, or identifying the client honestly to the wikis all meant editing source.

A value that IS set and is wrong fails here, at import, naming the variable — rather than surfacing
later as a confusing timeout or a 404 from an endpoint nobody realised was hardcoded.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from rs_mcp_server.version import VERSION_INFO


class ConfigError(ValueError):
    """A configuration value was supplied and is unusable."""


def _url(name: str, default: str) -> str:
    """An absolute http(s) URL. Trailing slashes are left alone — some of these are prefixes."""
    raw = os.environ.get(name, default).strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(
            f"Invalid {name}={raw!r}: must be an absolute http(s) URL (e.g. https://example.com/api.php)"
        )
    return raw


def _port(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError(
            f"Invalid {name}={raw!r}: must be an integer between 1 and 65535"
        ) from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"Invalid {name}={raw!r}: must be an integer between 1 and 65535")
    return port


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"Invalid {name}={raw!r}: must be a number of seconds") from None
    if value <= 0:
        raise ConfigError(f"Invalid {name}={raw!r}: must be greater than zero")
    return value


def _non_negative_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"Invalid {name}={raw!r}: must be a whole number") from None
    if value < 0:
        raise ConfigError(f"Invalid {name}={raw!r}: must not be negative")
    return value


# --------------------------------------------------------------------------------------------
# Where the server listens.
#
# 127.0.0.1 by default: a dev server that binds every interface the moment you run it is a
# surprise, not a convenience. The container sets MCP_HOST=0.0.0.0 explicitly, because there the
# whole point is to be reachable from the platform's network.
# --------------------------------------------------------------------------------------------
MCP_HOST: str = os.environ.get("MCP_HOST", "127.0.0.1")
MCP_PORT: int = _port("MCP_PORT", 8000)

# --------------------------------------------------------------------------------------------
# Outbound HTTP.
# --------------------------------------------------------------------------------------------
HTTP_TIMEOUT: float = _positive_float("HTTP_TIMEOUT", 10.0)
HTTP_MAX_RETRIES: int = _non_negative_int("HTTP_MAX_RETRIES", 2)

# The wikis ask that tools identify themselves. Overridable so a deployment can add a contact —
# "RS-MCP-Server/1.2 (+https://example.com/contact)" — without a code change.
USER_AGENT: str = os.environ.get("USER_AGENT", f"RS-MCP-Server/{VERSION_INFO['version']}")

# --------------------------------------------------------------------------------------------
# Upstream endpoints. Overridable so the server can be pointed at a mirror, a caching proxy, or a
# recorded fixture host — which is also what makes an offline test run possible without patching
# module internals.
# --------------------------------------------------------------------------------------------
WIKI_APIS: dict[str, str] = {
    "rs3": _url("RS3_WIKI_API", "https://runescape.wiki/api.php"),
    "osrs": _url("OSRS_WIKI_API", "https://oldschool.runescape.wiki/api.php"),
}

WIKI_BASE_URLS: dict[str, str] = {
    "rs3": _url("RS3_WIKI_BASE", "https://runescape.wiki/w/"),
    "osrs": _url("OSRS_WIKI_BASE", "https://oldschool.runescape.wiki/w/"),
}

OSRS_PRICES_BASE: str = _url("OSRS_PRICES_BASE", "https://prices.runescape.wiki/api/v1/osrs")

# The RS3 Grand Exchange catalogue-detail endpoint, and a secondary GE price catalogue — both used by
# get_item_price. These used to be literals in tools/prices.py, the last two upstream URLs that escaped
# this module's parameterization. GEPRICE_CATALOG_URL returns 403 today (one FVT case xfails on it);
# kept overridable so a working mirror can be pointed at without a code change.
RS3_GE_DETAIL_URL: str = _url(
    "RS3_GE_DETAIL_URL", "https://secure.runescape.com/m=itemdb_rs/api/catalogue/detail.json"
)
GEPRICE_CATALOG_URL: str = _url("GEPRICE_CATALOG_URL", "https://geprice.com/api/items")

# The two hiscores endpoints do not share a base — they are different products behind different
# `m=` paths — so each is its own variable rather than a base plus a suffix that only ever fits one.
HISCORES_URLS: dict[str, str] = {
    "rs3": _url("RS3_HISCORES_URL", "https://secure.runescape.com/m=hiscore/index_lite.json"),
    "osrs": _url(
        "OSRS_HISCORES_URL", "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json"
    ),
}
