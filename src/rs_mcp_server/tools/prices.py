"""get_item_price tool — OSRS and RS3 Grand Exchange APIs."""
import re
from rs_mcp_server import cache
from rs_mcp_server.logging import instrument
from ._http import http_get, WIKI_APIS, MW_BASE_PARAMS

_OSRS_MAPPING_URL    = "https://prices.runescape.wiki/api/v1/osrs/mapping"
_OSRS_LATEST_URL     = "https://prices.runescape.wiki/api/v1/osrs/latest"
_OSRS_5M_URL         = "https://prices.runescape.wiki/api/v1/osrs/5m"
_RS3_GE_DETAIL       = "https://secure.runescape.com/m=itemdb_rs/api/catalogue/detail.json"
_GEPRICE_CATALOG_URL = "https://geprice.com/api/items"

_TTL_PRICE    = 300    # 5 minutes
_TTL_MAPPING  = 86400  # 24 hours — only changes on game updates
_TTL_OSRS_5M  = 300    # 5 minutes — endpoint refreshes on the same cadence
_TTL_GEPRICE  = 3600   # 1 hour — geprice catalog refreshes weekly


@instrument("get_item_price")
async def get_item_price(item_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in ("rs3", "osrs"):
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

    cache_key = f"price:{game}:{item_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = await (_get_osrs_price(item_name) if game == "osrs" else _get_rs3_price(item_name))
    cache.set(cache_key, result, _TTL_PRICE)
    return result


# ---------------------------------------------------------------------------
# OSRS — prices.runescape.wiki
# ---------------------------------------------------------------------------

async def osrs_mapping() -> list[dict]:
    cached = cache.get("osrs:mapping")
    if cached is not None:
        return cached
    data = await http_get(_OSRS_MAPPING_URL)
    cache.set("osrs:mapping", data, _TTL_MAPPING)
    return data


async def _get_osrs_price(item_name: str) -> str:
    mapping = await osrs_mapping()
    query = item_name.lower()

    item = None
    for entry in mapping:
        if entry.get("name", "").lower() == query:
            item = entry
            break
    if item is None:
        for entry in mapping:
            if query in entry.get("name", "").lower():
                item = entry
                break

    if item is None:
        return f"Item '{item_name}' not found on the OSRS Grand Exchange."

    item_id = item["id"]
    canonical = item["name"]

    data = await http_get(_OSRS_LATEST_URL, params={"id": item_id})
    info = data.get("data", {}).get(str(item_id))
    if not info:
        return f"Price data unavailable for '{canonical}' (OSRS)."

    high = info.get("high")
    low  = info.get("low")

    lines = [f"**{canonical}** (OSRS Grand Exchange)"]
    if high:
        lines.append(f"Instant buy:  {high:,} gp")
    if low:
        lines.append(f"Instant sell: {low:,} gp")
    if high and low:
        lines.append(f"Spread:       {high - low:,} gp")

    five_min = await _osrs_5m_for(item_id)
    if five_min is not None:
        avg_high = five_min.get("avgHighPrice")
        avg_low  = five_min.get("avgLowPrice")
        vol_high = five_min.get("highPriceVolume")
        vol_low  = five_min.get("lowPriceVolume")
        if avg_high:
            lines.append(f"5-min avg buy:  {avg_high:,} gp  (volume: {vol_high or 0})")
        if avg_low:
            lines.append(f"5-min avg sell: {avg_low:,} gp  (volume: {vol_low or 0})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# RS3 — wiki Module:Exchange for item ID, then GE detail API for price
# ---------------------------------------------------------------------------

async def _rs3_item_id(item_name: str) -> tuple[int, str] | None:
    """Return (item_id, canonical_name) via RS3 wiki Exchange module, or None."""
    # Module:Exchange/<name> is case-sensitive; canonicalize first letter only (str.capitalize would clobber inner caps like "TzHaar-Ket-Om").
    canonical_title = item_name[:1].upper() + item_name[1:]
    params = {
        "action": "query",
        "titles": f"Module:Exchange/{canonical_title}",
        "prop": "revisions",
        "rvprop": "content",
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS["rs3"], params=params)

    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None

    content = pages[0].get("revisions", [{}])[0].get("content", "")
    id_match   = re.search(r"itemId\s*=\s*(\d+)", content)
    name_match = re.search(r"item\s*=\s*'([^']+)'", content)
    if not id_match:
        return None

    return int(id_match.group(1)), (name_match.group(1) if name_match else item_name)


async def _get_rs3_price(item_name: str) -> str:
    match = await _rs3_item_id(item_name)
    if match is None:
        # No GE module page — fall back to the geprice community catalog for
        # off-GE items (Tumeken's Resplendence pieces, Devourer's Nexus, etc.).
        street = await _geprice_lookup(item_name)
        if street is not None and street.get("currentWeekAverage", 0) > 0:
            return _format_geprice_only(street)
        return f"Item '{item_name}' not found on the RS3 Grand Exchange."

    item_id, canonical = match
    detail = (await http_get(_RS3_GE_DETAIL, params={"item": item_id})).get("item", {})

    price   = detail.get("current", {}).get("price", "N/A")
    trend   = detail.get("current", {}).get("trend", "")
    today_p = detail.get("today", {}).get("price", "")
    d30     = detail.get("day30", {}).get("change", "")
    d90     = detail.get("day90", {}).get("change", "")

    lines = [f"**{canonical}** (RS3 Grand Exchange)"]
    lines.append(f"Price:   {price} gp  ({trend})")
    if today_p:
        lines.append(f"Today:   {today_p} gp")
    if d30:
        lines.append(f"30-day:  {d30}")
    if d90:
        lines.append(f"90-day:  {d90}")

    street = await _geprice_lookup(canonical)
    if street is not None and street.get("currentWeekAverage", 0) > 0:
        change = street.get("weeklyChangePercent") or ""
        suffix = f"  ({change})" if change and change != "-" else ""
        lines.append(f"Street avg (this week): {street['currentWeekAverage']:,} gp{suffix}")

    return "\n".join(lines)


def _format_geprice_only(entry: dict) -> str:
    change = entry.get("weeklyChangePercent") or ""
    suffix = f"  ({change})" if change and change != "-" else ""
    return (
        f"**{entry['name']}** (RS3 community trades)\n"
        f"Street avg (this week): {entry['currentWeekAverage']:,} gp{suffix}"
    )


# ---------------------------------------------------------------------------
# OSRS 5-minute aggregates — best-effort enrichment, swallows fetch errors so a
# transient outage on the /5m endpoint doesn't break the primary GE response.
# ---------------------------------------------------------------------------

async def _osrs_5m_bulk() -> dict | None:
    cached = cache.get("osrs:5m:all")
    if cached is not None:
        return cached
    try:
        data = await http_get(_OSRS_5M_URL)
    except Exception:
        return None
    cache.set("osrs:5m:all", data, _TTL_OSRS_5M)
    return data


async def _osrs_5m_for(item_id: int) -> dict | None:
    bulk = await _osrs_5m_bulk()
    if bulk is None:
        return None
    return bulk.get("data", {}).get(str(item_id))


# ---------------------------------------------------------------------------
# geprice.com community catalog — RS3 off-GE / off-cap street prices for ~300
# high-end items. Returned blob is small; we cache the full catalog and look
# up by case-insensitive name.
# ---------------------------------------------------------------------------

async def _geprice_catalog() -> list[dict] | None:
    cached = cache.get("geprice:catalog")
    if cached is not None:
        return cached
    try:
        data = await http_get(_GEPRICE_CATALOG_URL)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    cache.set("geprice:catalog", data, _TTL_GEPRICE)
    return data


async def _geprice_lookup(name: str) -> dict | None:
    catalog = await _geprice_catalog()
    if not catalog:
        return None
    target = name.strip().casefold()
    for entry in catalog:
        if entry.get("name", "").casefold() == target:
            return entry
    return None
