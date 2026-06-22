"""get_player_stats tool — Jagex Hiscores JSON API."""
import re

import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import *
from ._http import http_get

_HISCORES_JSON_APIS = {
    "rs3":  "https://secure.runescape.com/m=hiscore/index_lite.json",
    "osrs": "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json",
}

# RuneScape display names are 1–12 chars: letters, digits, spaces, hyphens, underscores.
# Validating up front gives a clear message and avoids a 403 from the hiscores API on
# obviously-invalid input (e.g. punctuation).
_VALID_RSN = re.compile(r"[A-Za-z0-9 _-]{1,12}")


@instrument("get_player_stats")
async def get_player_stats(username: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in _HISCORES_JSON_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

    username = username.strip()
    if not username:
        return "Please provide a player username."
    invalid = validate_username(username)
    if invalid:
        return invalid

    cache_key = f"stats:{game}:{username.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        data = await http_get(_HISCORES_JSON_APIS[game], params={"player": username})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return (
                f"No public hiscores for '{username}' on {game.upper()} — "
                f"the account may not exist, or its hiscores are hidden in privacy settings."
            )
        return (
            f"Couldn't retrieve {game.upper()} hiscores for '{username}' right now "
            f"(the service returned HTTP {e.response.status_code}). Try again shortly."
        )
    except httpx.RequestError:
        return (
            f"Couldn't reach the {game.upper()} Hiscores right now — "
            f"the service may be temporarily unavailable. Try again shortly."
        )

    result = _format_stats(username, game, data)
    cache.set(cache_key, result, TTL_10MIN)
    return result


def _as_int(value: object) -> int:
    """Coerce a hiscores numeric field to int, tolerating strings, None, or malformed values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def validate_username(username: str) -> str | None:
    """Return an error message if `username` isn't a valid RSN format, else None.

    Callers handle the empty case themselves, since their messaging differs.
    """
    if not _VALID_RSN.fullmatch(username):
        return (
            f"'{username}' isn't a valid RuneScape name — names are 1–12 characters "
            f"(letters, digits, spaces, hyphens, or underscores)."
        )
    return None


def _format_stats(username: str, game: str, data: dict) -> str:
    skills = data.get("skills") or []
    activities = data.get("activities") or []

    overall = next((s for s in skills if s.get("name") == "Overall"), None)
    if overall is None:
        return f"No usable hiscores data for **{username}** ({game.upper()})."

    lines = [
        f"**{username}** ({game.upper()} Hiscores)",
        f"Total level: {_as_int(overall.get('level')):,}  ·  Rank: {_fmt_rank(_as_int(overall.get('rank')))}",
        "",
        "Skills:",
    ]
    for s in skills:
        if s.get("name") == "Overall":
            continue
        rank = _as_int(s.get("rank"))
        rank_s = f"rank {rank:,}" if rank > 0 else "unranked"
        lines.append(f"  {s.get('name', ''):<14} {_as_int(s.get('level')):>3}   ({rank_s})")

    ranked = [a for a in activities if _as_int(a.get("rank", -1)) > 0]
    if ranked:
        lines += ["", "Activities:"]
        for a in ranked:
            lines.append(
                f"  {a.get('name', ''):<35} {_as_int(a.get('score')):>12,}   (rank {_as_int(a.get('rank')):,})"
            )

    return "\n".join(lines)


def _fmt_rank(rank: int) -> str:
    return f"{rank:,}" if rank > 0 else "—"
