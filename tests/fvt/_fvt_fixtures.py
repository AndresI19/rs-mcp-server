"""Fixtures and case data for function-verification tests against a live MCP server.

The target is parameterised by environment, so the same suite runs against two things without
changing a line of test code:

| Target                          | FVT_BASE_URL           | FVT_MCP_PATH   | FVT_TRANSPORT     | FVT_BEARER |
|---------------------------------|------------------------|----------------|-------------------|------------|
| the container directly (default)| http://localhost:8000  | /sse           | sse               | —          |
| through the open-vMCP gateway   | http://localhost:8001  | /mcp/rs-mcp    | streamable-http   | required   |

The gateway's per-server route is a 1:1 passthrough, so the tool names and arguments are identical
either way — only the connection changes. Running through the gateway is what makes the calls show
up in its dashboard, since that is where the proxy records them.
"""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {
    "search_wiki",
    "get_item_price",
    "get_player_stats",
    "get_quest_info",
    "get_item_recipe",
    "get_equipment_stats",
    "get_monster_info",
    "get_item_drop_sources",
    "get_achievement",
    "get_player_achievement_progress",
    "get_money_makers",
    "get_money_maker_method",
    "get_best_alchables",
    "get_game_setting",
    "solve_clue",
    "solve_celtic_knot",
    "solve_sliding_puzzle",
}

# (tool_name, args, expected_substrings) — every substring must appear in the tool's text output.
CASES: list[tuple[str, dict, list[str]]] = [
    ("search_wiki", {"query": "fishing", "game": "rs3"}, ["**Fishing**", "Wiki)"]),
    ("search_wiki", {"query": "ardougne", "game": "osrs"}, ["OSRS Wiki)"]),
    (
        "search_wiki",
        {"query": "Trimmed masterwork", "game": "rs3"},
        ["**Trimmed masterwork", "RS3 Wiki"],
    ),
    (
        "get_item_price",
        {"item_name": "shark", "game": "osrs"},
        ["**Shark**", "OSRS Grand Exchange", "Instant buy:", "5-min avg"],
    ),
    (
        "get_item_price",
        {"item_name": "Abyssal whip", "game": "rs3"},
        ["**Abyssal whip**", "RS3 Grand Exchange", "Price:"],
    ),
    (
        "get_item_price",
        {"item_name": "Mask of Tumeken's Resplendence", "game": "rs3"},
        ["**Mask of Tumeken's Resplendence**", "community trades", "Street"],
    ),
    ("get_item_price", {"item_name": "", "game": "osrs"}, ["No item name provided"]),
    (
        "get_player_stats",
        {"username": "Lynx Titan", "game": "osrs"},
        ["OSRS Hiscores", "Total level"],
    ),
    ("get_player_stats", {"username": "Zezima", "game": "rs3"}, ["RS3 Hiscores", "Total level"]),
    (
        "get_player_stats",
        {"username": "ThisNameIsTooLong", "game": "osrs"},
        ["isn't a valid RuneScape name"],
    ),
    (
        "get_quest_info",
        {"quest_name": "Cook's Assistant", "game": "osrs"},
        ["**Cook's Assistant**", "Difficulty"],
    ),
    (
        "get_quest_info",
        {"quest_name": "Dragon Slayer", "game": "rs3"},
        ["**Dragon Slayer**", "Difficulty"],
    ),
    ("get_quest_info", {"quest_name": "Dragon Slayer I", "game": "rs3"}, ["Did you mean"]),
    ("get_quest_info", {"quest_name": "zzznotaquestzzz", "game": "rs3"}, ["No quest found"]),
    (
        "get_item_recipe",
        {"item_name": "Masterwork bow", "game": "rs3"},
        ["**Masterwork bow**", "Fletching", "Output:"],
    ),
    (
        "get_item_recipe",
        {"item_name": "Mithril platebody", "game": "osrs"},
        ["**Mithril platebody**", "Smithing", "Output:"],
    ),
    (
        "get_equipment_stats",
        {"item_name": "Abyssal whip", "game": "osrs"},
        ["**Abyssal whip**", "OSRS Wiki", "Slot:", "Attack slash:", "Strength:"],
    ),
    (
        "get_equipment_stats",
        {"item_name": "Abyssal whip", "game": "rs3"},
        ["**Abyssal whip**", "RS3 Wiki", "Tier:", "Damage:", "Accuracy:"],
    ),
    (
        "get_equipment_stats",
        {"item_name": "Trimmed masterwork melee helm", "game": "rs3"},
        ["**Trimmed masterwork melee helm**", "Tier:", "Set bonus"],
    ),
    (
        "get_monster_info",
        {"monster_name": "Abyssal demon", "game": "osrs"},
        ["**Abyssal demon**", "OSRS Wiki", "Combat level:", "Hitpoints:", "Slayer level:"],
    ),
    (
        "get_monster_info",
        {"monster_name": "Tormented demon", "game": "rs3"},
        ["**Tormented demon**", "RS3 Wiki", "Combat level:", "Life points:", "Weakness:"],
    ),
    (
        "get_item_drop_sources",
        {"item_name": "Abyssal whip", "game": "osrs"},
        ["**Drop sources for Abyssal whip**", "OSRS Wiki", "Abyssal demon", "1/512"],
    ),
    (
        "get_item_drop_sources",
        {"item_name": "Dragon bones", "game": "rs3"},
        ["**Drop sources for Dragon bones**", "RS3 Wiki"],
    ),
    (
        "get_achievement",
        {"name": "Noxious Foe", "game": "osrs"},
        ["**Noxious Foe**", "Combat Achievement", "OSRS Wiki", "Tier:"],
    ),
    (
        "get_achievement",
        {"name": "Falador Diary", "game": "osrs"},
        ["**Falador Diary**", "Achievement Diary", "OSRS Wiki", "Areas:"],
    ),
    (
        "get_achievement",
        {"name": "The Essence of Magic", "game": "rs3"},
        ["**The Essence of Magic**", "Achievement", "RS3 Wiki", "Score:"],
    ),
    (
        "get_player_achievement_progress",
        {"name": "Noxious Foe", "username": "Lynx Titan", "game": "osrs"},
        ["**Noxious Foe**", "Progress for Lynx Titan"],
    ),
    (
        "get_player_achievement_progress",
        {"name": "Noxious Foe", "username": "ThisNameIsTooLong", "game": "osrs"},
        ["isn't a valid RuneScape name"],
    ),
    (
        "get_money_makers",
        {"game": "osrs", "limit": 5},
        ["money-making methods (OSRS)", "GP/hr", "Category"],
    ),
    (
        "get_money_makers",
        {"game": "rs3", "limit": 5, "category": "combat"},
        ["money-making methods (RS3)", "Category", "Combat"],
    ),
    (
        "get_money_maker_method",
        {"method_name": "Bird house trapping", "game": "osrs"},
        ["**Bird house trapping**", "Category", "Inputs"],
    ),
    (
        "get_money_maker_method",
        {"method_name": "zzznotamethodzzz", "game": "rs3"},
        ["No money-making method found"],
    ),
    (
        "get_best_alchables",
        {"game": "osrs"},
        ["**Best Alchables (OSRS)**", "Category", "Nature rune"],
    ),
    (
        "get_best_alchables",
        {"game": "rs3"},
        ["**Best Alchables (RS3)** — passive", "Easy buys", "Slow buys"],
    ),
    (
        "get_best_alchables",
        {"game": "rs3", "mode": "manual"},
        ["**Best Alchables (RS3)** — manual", "Category"],
    ),
    (
        "get_game_setting",
        {"setting_name": "Hide roofs", "game": "osrs"},
        ["**Hide roofs**", "OSRS Wiki", "Settings#"],
    ),
    (
        "get_game_setting",
        {"setting_name": "Move Camera Up (Primary)", "game": "rs3"},
        ["**Move Camera Up (Primary)**", "RS3 Wiki", "Controls"],
    ),
    (
        "get_game_setting",
        {"setting_name": "zzznotasettingzzz", "game": "osrs"},
        ["No matching setting"],
    ),
    (
        "get_game_setting",
        {"setting_name": "follower", "game": "rs3"},
        ["Couldn't find an exact setting", "follower"],
    ),
    (
        "solve_clue",
        {"clue_text": "AN EARL", "game": "osrs", "clue_format": "anagram"},
        ["**AN EARL**", "Ranael", "Beginner anagram"],
    ),
    (
        "solve_clue",
        {"clue_text": "lumbridge", "game": "osrs", "clue_format": "cryptic"},
        ["Did you mean", "Lumbridge"],
    ),
    (
        "solve_clue",
        {"clue_text": "aris", "game": "osrs", "clue_format": "emote"},
        ["Did you mean", "Aris"],
    ),
    (
        "solve_clue",
        {"clue_text": "BMJ UIF LFCBC TFMMFS", "game": "osrs", "clue_format": "cipher"},
        ["**BMJ UIF LFCBC TFMMFS**", "Ali the Kebab", "Pollnivneach"],
    ),
    (
        "solve_clue",
        {"clue_text": "animals are in the Ardougne Zoo", "game": "rs3", "clue_format": "challenge"},
        ["Did you mean", "Ardougne Zoo", "challenge"],
    ),
    (
        "solve_clue",
        {"clue_text": "00 degrees 05 minutes south, 01 degrees 13 minutes east", "game": "rs3"},
        ["Medium coordinate", "Location"],
    ),
    (
        "solve_clue",
        {"clue_text": "I have a hand drawn treasure map", "game": "osrs"},
        ["This looks like", "Guide/Maps"],
    ),
    (
        "solve_clue",
        {"clue_text": "chest in the Duke of Lumbridge", "game": "rs3", "clue_format": "simple"},
        ["Did you mean", "Duke of Lumbridge", "simple"],
    ),
    ("solve_clue", {"clue_text": "compass clue", "game": "rs3"}, ["Compass clue", "arrow"]),
    ("solve_clue", {"clue_text": "zzznotaclue", "game": "osrs"}, ["No matching clue"]),
    ("solve_celtic_knot", {}, ["Reading a Celtic knot", "intersections"]),
    (
        "solve_celtic_knot",
        {
            "rings": [[4, 1, 2, 3], [6, 7, 1, 5], [5, 3, 9, 8]],
            "intersections": [[0, 0, 1, 0], [1, 1, 2, 1], [0, 2, 2, 2]],
        },
        ["Celtic knot solution", "Ring 0", "Ring 2"],
    ),
    ("solve_sliding_puzzle", {}, ["Reading a puzzle box", "perfect square"]),
    (
        "solve_sliding_puzzle",
        {"grid": [0, 1, 2, None, 3, 4, 6, 7, 5]},
        ["Puzzle box solution", "Click row"],
    ),
]


def case_id(case: tuple[str, dict, list[str]]) -> str:
    """Build a readable parametrize ID from a (tool, args, expected) case tuple."""
    tool, args, _ = case
    key_arg = next(
        (
            str(args[k])
            for k in (
                "query",
                "item_name",
                "username",
                "quest_name",
                "monster_name",
                "name",
                "method_name",
                "setting_name",
                "clue_text",
            )
            if k in args
        ),
        "",
    )
    game = args.get("game", "")
    parts = [tool]
    if game:
        parts.append(game)
    if key_arg:
        parts.append(key_arg.replace(" ", "_"))
    return "-".join(parts)


CASE_IDS = [case_id(c) for c in CASES]

# Cases whose upstream is currently broken, keyed by case id. They still *run* — the call is made,
# so the traffic runner exercises the tool and the gateway records it — they just do not fail the
# build. strict=False on purpose: if the upstream comes back, the case XPASSes rather than erroring,
# and the entry here can simply be deleted.
KNOWN_BROKEN: dict[str, str] = {
    "get_item_price-rs3-Mask_of_Tumeken's_Resplendence": (
        "geprice.com/api/items returns 403 (bot-blocked), so the off-GE street-price fallback in "
        "_geprice_lookup has no data source and every off-GE RS3 item reports 'not found'"
    ),
}


def _params() -> list:
    """CASES as pytest params, with the known-broken upstreams marked xfail rather than removed."""
    out = []
    for c in CASES:
        cid = case_id(c)
        marks = (
            [pytest.mark.xfail(reason=KNOWN_BROKEN[cid], strict=False)]
            if cid in KNOWN_BROKEN
            else []
        )
        out.append(pytest.param(*c, id=cid, marks=marks))
    return out


CASE_PARAMS = _params()


# Where to point the suite. Defaults reproduce the original behaviour exactly: SSE straight at the
# container on localhost:8000, no auth.
BASE_URL = os.environ.get("FVT_BASE_URL", "http://localhost:8000").rstrip("/")
MCP_PATH = os.environ.get("FVT_MCP_PATH", "/sse")
TRANSPORT = os.environ.get("FVT_TRANSPORT", "sse")
BEARER = os.environ.get("FVT_BEARER", "")

MCP_URL = f"{BASE_URL}{MCP_PATH}"
HEADERS = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}


@pytest.fixture(scope="session")
def live_server_url() -> str:
    """Skip the entire FVT session unless the target's /health answers.

    Both the server and the gateway expose /health at the root, so one probe covers both targets.
    """
    try:
        httpx.get(f"{BASE_URL}/health", timeout=2.0).raise_for_status()
    except Exception as e:
        pytest.skip(f"FVT requires a live MCP endpoint at {BASE_URL} ({type(e).__name__}: {e})")
    return BASE_URL


@pytest.fixture(scope="session")
async def mcp_session(live_server_url: str) -> AsyncIterator[ClientSession]:
    """Single MCP session reused across all FVT cases — one handshake per session."""
    if TRANSPORT == "streamable-http":
        # Unlike sse_client, this one takes no `headers=`: auth is carried by a caller-supplied
        # httpx client. That is where the gateway's bearer goes.
        # It also yields a third element (a session-id getter) that ClientSession does not take,
        # so the streams are unpacked rather than splatted.
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as http:
            async with streamable_http_client(MCP_URL, http_client=http) as (read, write, _sid):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
    elif TRANSPORT == "sse":
        async with sse_client(MCP_URL, headers=HEADERS) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session
    else:
        raise ValueError(f"FVT_TRANSPORT must be 'sse' or 'streamable-http', got {TRANSPORT!r}")
