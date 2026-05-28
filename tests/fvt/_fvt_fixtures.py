"""Fixtures and case data for function-verification tests against a live MCP server."""
from collections.abc import AsyncIterator

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


EXPECTED_TOOLS = {
    "search_wiki",
    "get_item_price",
    "get_player_stats",
    "get_quest_info",
    "get_item_recipe",
    "get_equipment_stats",
    "get_monster_info",
    "get_achievement",
    "get_money_makers",
    "get_money_maker_method",
    "get_best_alchables",
    "get_game_setting",
    "solve_clue",
}

# (tool_name, args, expected_substrings) — every substring must appear in the tool's text output.
CASES: list[tuple[str, dict, list[str]]] = [
    ("search_wiki",         {"query": "fishing", "game": "rs3"},                                            ["**Fishing**", "Wiki)"]),
    ("search_wiki",         {"query": "ardougne", "game": "osrs"},                                          ["OSRS Wiki)"]),
    ("get_item_price",      {"item_name": "shark", "game": "osrs"},                                         ["**Shark**", "OSRS Grand Exchange", "Instant buy:", "5-min avg"]),
    ("get_item_price",      {"item_name": "Abyssal whip", "game": "rs3"},                                   ["**Abyssal whip**", "RS3 Grand Exchange", "Price:"]),
    ("get_item_price",      {"item_name": "Mask of Tumeken's Resplendence", "game": "rs3"},                 ["**Mask of Tumeken's Resplendence**", "community trades", "Street"]),
    ("get_player_stats",    {"username": "Lynx Titan", "game": "osrs"},                                     ["OSRS Hiscores", "Total level"]),
    ("get_player_stats",    {"username": "Zezima", "game": "rs3"},                                          ["RS3 Hiscores", "Total level"]),
    ("get_quest_info",      {"quest_name": "Cook's Assistant", "game": "osrs"},                             ["**Cook's Assistant**", "Difficulty"]),
    ("get_quest_info",      {"quest_name": "Dragon Slayer", "game": "rs3"},                                 ["**Dragon Slayer**", "Difficulty"]),
    ("get_quest_info",      {"quest_name": "Dragon Slayer I", "game": "rs3"},                               ["Did you mean"]),
    ("get_quest_info",      {"quest_name": "zzznotaquestzzz", "game": "rs3"},                               ["No quest found"]),
    ("get_item_recipe",     {"item_name": "Masterwork bow", "game": "rs3"},                                 ["**Masterwork bow**", "Fletching", "Output:"]),
    ("get_item_recipe",     {"item_name": "Mithril platebody", "game": "osrs"},                             ["**Mithril platebody**", "Smithing", "Output:"]),
    ("get_equipment_stats", {"item_name": "Abyssal whip", "game": "osrs"},                                  ["**Abyssal whip**", "OSRS Wiki", "Slot:", "Attack slash:", "Strength:"]),
    ("get_equipment_stats", {"item_name": "Abyssal whip", "game": "rs3"},                                   ["**Abyssal whip**", "RS3 Wiki", "Tier:", "Damage:", "Accuracy:"]),
    ("get_monster_info",    {"monster_name": "Abyssal demon", "game": "osrs"},                              ["**Abyssal demon**", "OSRS Wiki", "Combat level:", "Hitpoints:", "Slayer level:"]),
    ("get_monster_info",    {"monster_name": "Tormented demon", "game": "rs3"},                             ["**Tormented demon**", "RS3 Wiki", "Combat level:", "Life points:", "Weakness:"]),
    ("get_achievement",     {"name": "Noxious Foe", "game": "osrs"},                                        ["**Noxious Foe**", "Combat Achievement", "OSRS Wiki", "Tier:"]),
    ("get_achievement",     {"name": "Falador Diary", "game": "osrs"},                                      ["**Falador Diary**", "Achievement Diary", "OSRS Wiki", "Areas:"]),
    ("get_achievement",     {"name": "The Essence of Magic", "game": "rs3"},                                ["**The Essence of Magic**", "Achievement", "RS3 Wiki", "Score:"]),
    ("get_money_makers",       {"game": "osrs", "limit": 5},                                                ["money-making methods (OSRS)", "GP/hr", "Category"]),
    ("get_money_makers",       {"game": "rs3", "limit": 5, "category": "combat"},                           ["money-making methods (RS3)", "Category", "Combat"]),
    ("get_money_maker_method", {"method_name": "Bird house trapping", "game": "osrs"},                      ["**Bird house trapping**", "Category", "Inputs"]),
    ("get_money_maker_method", {"method_name": "zzznotamethodzzz", "game": "rs3"},                          ["No money-making method found"]),
    ("get_best_alchables",     {"game": "osrs"},                                                            ["**Best Alchables (OSRS)**", "Category", "Nature rune"]),
    ("get_best_alchables",     {"game": "rs3"},                                                             ["**Best Alchables (RS3)** — passive", "Easy buys", "Slow buys"]),
    ("get_best_alchables",     {"game": "rs3", "mode": "manual"},                                           ["**Best Alchables (RS3)** — manual", "Category"]),
    ("get_game_setting",       {"setting_name": "Hide roofs", "game": "osrs"},                              ["**Hide roofs**", "OSRS Wiki", "Settings#"]),
    ("get_game_setting",       {"setting_name": "Move Camera Up (Primary)", "game": "rs3"},                 ["**Move Camera Up (Primary)**", "RS3 Wiki", "Controls"]),
    ("get_game_setting",       {"setting_name": "zzznotasettingzzz", "game": "osrs"},                       ["No matching setting"]),
    ("solve_clue",             {"clue_text": "AN EARL", "game": "osrs", "clue_format": "anagram"},          ["**AN EARL**", "Ranael", "Beginner anagram"]),
    ("solve_clue",             {"clue_text": "lumbridge", "game": "osrs", "clue_format": "cryptic"},        ["Did you mean", "Lumbridge"]),
    ("solve_clue",             {"clue_text": "aris", "game": "osrs", "clue_format": "emote"},               ["Did you mean", "Aris"]),
    ("solve_clue",             {"clue_text": "BMJ UIF LFCBC TFMMFS", "game": "osrs", "clue_format": "cipher"}, ["**BMJ UIF LFCBC TFMMFS**", "Ali the Kebab", "Pollnivneach"]),
    ("solve_clue",             {"clue_text": "zzznotaclue", "game": "osrs"},                                ["No matching clue"]),
]


def case_id(case: tuple[str, dict, list[str]]) -> str:
    """Build a readable parametrize ID from a (tool, args, expected) case tuple."""
    tool, args, _ = case
    key_arg = next(
        (str(args[k]) for k in ("query", "item_name", "username", "quest_name", "monster_name",
                                "name", "method_name", "setting_name", "clue_text") if k in args),
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


@pytest.fixture(scope="session")
def live_server_url() -> str:
    """Skip the entire FVT session unless an MCP server is reachable on localhost:8000."""
    url = "http://localhost:8000"
    try:
        httpx.get(f"{url}/health", timeout=2.0).raise_for_status()
    except Exception as e:
        pytest.skip(f"FVT requires a running rs-mcp-server on {url} ({type(e).__name__}: {e})")
    return url


@pytest.fixture(scope="session")
async def mcp_session(live_server_url: str) -> AsyncIterator[ClientSession]:
    """Single MCP session reused across all FVT cases — one handshake per session."""
    async with sse_client(f"{live_server_url}/sse") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session
