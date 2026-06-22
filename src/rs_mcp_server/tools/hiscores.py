"""get_player_stats tool — Jagex Hiscores JSON API."""
import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import http_get

_HISCORES_JSON_APIS = {
    "rs3":  "https://secure.runescape.com/m=hiscore/index_lite.json",
    "osrs": "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json",
}

_TTL_STATS = 600  # 10 minutes


@instrument("get_player_stats")
async def get_player_stats(username: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in _HISCORES_JSON_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

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
        raise
    except httpx.RequestError:
        return (
            f"Couldn't reach the {game.upper()} Hiscores right now — "
            f"the service may be temporarily unavailable. Try again shortly."
        )

    result = _format_stats(username, game, data)
    cache.set(cache_key, result, _TTL_STATS)
    return result


def _format_stats(username: str, game: str, data: dict) -> str:
    skills = data.get("skills") or []
    activities = data.get("activities") or []

    overall = next((s for s in skills if s.get("name") == "Overall"), None)
    if overall is None:
        return f"No usable hiscores data for **{username}** ({game.upper()})."

    lines = [
        f"**{username}** ({game.upper()} Hiscores)",
        f"Total level: {overall['level']:,}  ·  Rank: {_fmt_rank(overall['rank'])}",
        "",
        "Skills:",
    ]
    for s in skills:
        if s.get("name") == "Overall":
            continue
        rank_s = f"rank {s['rank']:,}" if s['rank'] > 0 else "unranked"
        lines.append(f"  {s['name']:<14} {s['level']:>3}   ({rank_s})")

    ranked = [a for a in activities if a.get("rank", -1) > 0]
    if ranked:
        lines += ["", "Activities:"]
        for a in ranked:
            lines.append(f"  {a['name']:<35} {a['score']:>12,}   (rank {a['rank']:,})")

    return "\n".join(lines)


def _fmt_rank(rank: int) -> str:
    return f"{rank:,}" if rank > 0 else "—"
