"""get_item_price tool — RS3 Grand Exchange API."""
import httpx
import cache

_GE_API = "https://services.runescape.com/m=itemdb_rs/api/catalogue/detail.json"
_TTL = 300  # 5 minutes


async def get_item_price(item_name: str) -> str:
    cache_key = f"price:{item_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    raise NotImplementedError("get_item_price not yet implemented")
