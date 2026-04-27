"""get_player_stats and get_quest_info tools — Jagex Hiscores and Wiki APIs."""
import httpx
import cache

_HISCORES_API = "https://secure.runescape.com/m=hiscore/index_lite.ws"
_TTL_STATS = 600   # 10 minutes
_TTL_QUESTS = 3600  # 1 hour


async def get_player_stats(username: str) -> str:
    cache_key = f"stats:{username}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    raise NotImplementedError("get_player_stats not yet implemented")


async def get_quest_info(quest_name: str) -> str:
    cache_key = f"quest:{quest_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    raise NotImplementedError("get_quest_info not yet implemented")
