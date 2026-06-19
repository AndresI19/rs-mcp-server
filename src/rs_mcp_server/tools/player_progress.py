"""get_player_achievement_progress — pairs wiki achievement info with player hiscores data."""
import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import http_get
from .achievements import _dispatch, _fetch_page, _parse_fields, _titles_match, get_achievement
from .hiscores import _HISCORES_JSON_APIS

_TTL_PROGRESS = 600


@instrument("get_player_achievement_progress")
async def get_player_achievement_progress(name: str, username: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in _HISCORES_JSON_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not name.strip() or not username.strip():
        return "Both an achievement name and a username are required."

    cache_key = f"progress:{game}:{name.lower()}:{username.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    info = await get_achievement(name, game)
    if info.startswith(("No achievement found", "Did you mean", "Unknown game")):
        return info

    direct = await _fetch_page(name, game, follow_redirects=True)
    kind, monster = None, None
    if direct is not None and _titles_match(name, direct["title"]):
        match = _dispatch(direct["content"])
        if match is not None:
            body, _fields_def, kind = match
            monster = _parse_fields(body).get("monster")

    try:
        data = await http_get(_HISCORES_JSON_APIS[game], params={"player": username})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            result = (
                f"{info}\n\n"
                f"**Progress for {username}:** No public hiscores — the account may not "
                f"exist, or its hiscores are hidden in privacy settings."
            )
            cache.set(cache_key, result, _TTL_PROGRESS)
            return result
        raise

    progress = _format_progress(kind, monster, username, data)
    result = f"{info}\n\n{progress}"
    cache.set(cache_key, result, _TTL_PROGRESS)
    return result


def _format_progress(kind: str | None, monster: str | None, username: str, data: dict) -> str:
    lines = [f"**Progress for {username}:**"]

    if kind == "Combat Achievement" and monster:
        activity = _find_activity(data.get("activities") or [], monster)
        if activity is not None:
            if activity["rank"] > 0:
                lines.append(f"  {activity['name']}: {activity['score']:,} KCs  (rank {activity['rank']:,})")
            else:
                lines.append(f"  {activity['name']}: not yet ranked (no recorded kills)")
            lines.append("  Note: per-task CA completion isn't in public hiscores; the KC above is an engagement signal.")
        else:
            lines.append(f"  '{monster}' isn't in the public hiscores boss list. Per-task CA completion isn't tracked there either.")
        lines.append("  See the in-game adventurer's log for per-task completion status.")
    elif kind == "Achievement Diary":
        lines.append("  Achievement Diary completion isn't in public hiscores.")
        lines.append("  See the in-game Achievement Diary tab for completion status.")
    elif kind == "Achievement":
        lines.append("  Per-task achievement completion isn't in public hiscores.")
        lines.append("  See the in-game adventurer's log or RuneMetrics for completion status.")
    else:
        lines.append("  This achievement type isn't directly trackable from public hiscores.")

    return "\n".join(lines)


def _find_activity(activities: list[dict], monster: str) -> dict | None:
    target = monster.strip().casefold()
    for a in activities:
        if (a.get("name") or "").strip().casefold() == target:
            return a
    return None
