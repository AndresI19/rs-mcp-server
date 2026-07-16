"""get_player_achievement_progress — pairs wiki achievement info with player hiscores data."""

import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import TTL_10MIN
from ._http import http_get
from ._registry import ToolSpec, game_param, normalize_game, object_schema, register
from .achievements import _dispatch, _fetch_page, _parse_fields, _titles_match, get_achievement
from .hiscores import _HISCORES_JSON_APIS, _as_int, validate_username


@instrument("get_player_achievement_progress")
async def get_player_achievement_progress(name: str, username: str, game: str = "rs3") -> str:
    game, err = normalize_game(game, _HISCORES_JSON_APIS)
    if err:
        return err
    if not name.strip() or not username.strip():
        return "Both an achievement name and a username are required."
    invalid = validate_username(username.strip())
    if invalid:
        return invalid

    cache_key = f"progress:{game}:{name.lower()}:{username.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    info = await get_achievement(name, game)
    if info.startswith(
        ("No achievement found", "Did you mean", "Unknown game", "Multiple tiered variants")
    ):
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
            note = (
                "No public hiscores — the account may not exist, or its hiscores "
                "are hidden in privacy settings."
            )
        else:
            note = f"Couldn't retrieve hiscores right now (HTTP {e.response.status_code}). Try again shortly."
        result = f"{info}\n\n**Progress for {username}:** {note}"
        cache.set(cache_key, result, TTL_10MIN)
        return result
    except httpx.RequestError:
        return (
            f"{info}\n\n**Progress for {username}:** Couldn't reach the hiscores service "
            f"right now. Try again shortly."
        )

    progress = _format_progress(kind, monster, username, data)
    result = f"{info}\n\n{progress}"
    cache.set(cache_key, result, TTL_10MIN)
    return result


def _format_progress(kind: str | None, monster: str | None, username: str, data: dict) -> str:
    lines = [f"**Progress for {username}:**"]

    if kind == "Combat Achievement" and monster:
        activity = _find_activity(data.get("activities") or [], monster)
        if activity is not None:
            rank = _as_int(activity.get("rank"))
            if rank > 0:
                lines.append(
                    f"  {activity.get('name', '')}: {_as_int(activity.get('score')):,} KCs  (rank {rank:,})"
                )
            else:
                lines.append(f"  {activity.get('name', '')}: not yet ranked (no recorded kills)")
            lines.append(
                "  Note: per-task CA completion isn't in public hiscores; the KC above is an engagement signal."
            )
        else:
            lines.append(
                f"  '{monster}' isn't in the public hiscores boss list. Per-task CA completion isn't tracked there either."
            )
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


TOOL = register(
    ToolSpec(
        name="get_player_achievement_progress",
        description="Pair wiki achievement info with a specific player's hiscores. For OSRS Combat Achievements that target a boss listed in public hiscores, surfaces that boss's kill count for the player. For Achievement Diaries (OSRS) and per-task achievements (RS3), the tool is honest that completion isn't in public hiscores and points to the in-game adventurer's log.",
        input_schema=object_schema(
            {
                "name": {"type": "string", "description": "The achievement name."},
                "username": {
                    "type": "string",
                    "description": "The player's RuneScape username.",
                },
                "game": game_param(
                    "Which game to query: 'rs3' (default) or 'osrs'.",
                ),
            },
            required=["name", "username"],
        ),
        invoke=lambda args: get_player_achievement_progress(
            args["name"], args["username"], args.get("game", "rs3")
        ),
    )
)
