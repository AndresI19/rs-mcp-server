"""get_player_stats tool — Jagex Hiscores API."""
import httpx
from rs_mcp_server import cache
from ._http import http_get_text

_HISCORES_APIS = {
    "rs3":  "https://secure.runescape.com/m=hiscore/index_lite.ws",
    "osrs": "https://secure.runescape.com/m=hiscore_oldschool/index_lite.ws",
}

_OSRS_SKILLS = (
    "Overall", "Attack", "Defence", "Strength", "Hitpoints", "Ranged", "Prayer",
    "Magic", "Cooking", "Woodcutting", "Fletching", "Fishing", "Firemaking",
    "Crafting", "Smithing", "Mining", "Herblore", "Agility", "Thieving",
    "Slayer", "Farming", "Runecraft", "Hunter", "Construction",
)

_RS3_SKILLS = (
    "Overall", "Attack", "Defence", "Strength", "Constitution", "Ranged",
    "Prayer", "Magic", "Cooking", "Woodcutting", "Fletching", "Fishing",
    "Firemaking", "Crafting", "Smithing", "Mining", "Herblore", "Agility",
    "Thieving", "Slayer", "Farming", "Runecrafting", "Hunter", "Construction",
    "Summoning", "Dungeoneering", "Divination", "Invention", "Archaeology",
    "Necromancy",
)

_TTL_STATS = 600   # 10 minutes


async def get_player_stats(username: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in _HISCORES_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

    cache_key = f"stats:{game}:{username.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        csv = await http_get_text(_HISCORES_APIS[game], params={"player": username})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Player '{username}' not found on {game.upper()} Hiscores."
        raise

    skills = _OSRS_SKILLS if game == "osrs" else _RS3_SKILLS
    result = _format_stats(username, game, csv, skills)
    cache.set(cache_key, result, _TTL_STATS)
    return result


def _format_stats(username: str, game: str, csv: str, skills: tuple[str, ...]) -> str:
    lines = csv.strip().splitlines()
    rows = []
    for i, name in enumerate(skills):
        if i >= len(lines):
            break
        parts = lines[i].split(",")
        if len(parts) < 2:
            continue
        try:
            rank = int(parts[0])
            level = int(parts[1])
        except ValueError:
            continue
        rows.append((name, level, rank))

    if not rows:
        return f"No usable hiscores data for **{username}** ({game.upper()})."

    overall_name, overall_level, overall_rank = rows[0]
    header = f"**{username}** ({game.upper()} Hiscores)"
    summary = f"Total level: {overall_level:,}  ·  Rank: {_fmt_rank(overall_rank)}"

    skill_lines = []
    for name, level, rank in rows[1:]:
        rank_s = f"rank {rank:,}" if rank > 0 else "unranked"
        skill_lines.append(f"  {name:<14} {level:>3}   ({rank_s})")

    return "\n".join([header, summary, ""] + skill_lines)


def _fmt_rank(rank: int) -> str:
    return f"{rank:,}" if rank > 0 else "—"
