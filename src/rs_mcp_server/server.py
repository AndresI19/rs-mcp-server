"""RuneScape MCP Server — HTTP/SSE entry point."""

import os
import sys
import threading
import traceback
from contextlib import asynccontextmanager

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from rs_mcp_server.config import MCP_HOST, MCP_PORT
from rs_mcp_server.logging import setup_logging
from rs_mcp_server.tools.achievements import get_achievement
from rs_mcp_server.tools.alchables import get_best_alchables
from rs_mcp_server.tools.celtic_knot import solve_celtic_knot
from rs_mcp_server.tools.clues import solve_clue
from rs_mcp_server.tools.drops import get_item_drop_sources
from rs_mcp_server.tools.equipment import get_equipment_stats
from rs_mcp_server.tools.hiscores import get_player_stats
from rs_mcp_server.tools.moneymakers import get_money_maker_method, get_money_makers
from rs_mcp_server.tools.monsters import get_monster_info
from rs_mcp_server.tools.player_progress import get_player_achievement_progress
from rs_mcp_server.tools.prices import get_item_price
from rs_mcp_server.tools.quests import get_quest_info
from rs_mcp_server.tools.recipes import get_item_recipe
from rs_mcp_server.tools.settings import get_game_setting
from rs_mcp_server.tools.sliding_puzzle import solve_sliding_puzzle
from rs_mcp_server.tools.wiki import search_wiki
from rs_mcp_server.version import VERSION_INFO

setup_logging()


def _excepthook(exc_type, exc_value, exc_tb):
    frames = "".join(traceback.format_tb(exc_tb, limit=3))
    print(
        f"\nServer terminated — {exc_type.__name__}: {exc_value}\n{frames}",
        file=sys.stderr,
        flush=True,
    )


def _thread_excepthook(args):
    _excepthook(args.exc_type, args.exc_value, args.exc_traceback)
    os._exit(1)


sys.excepthook = _excepthook
threading.excepthook = _thread_excepthook

app = Server("rs-mcp-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_wiki",
            description="Search the RuneScape Wiki for information about items, quests, skills, monsters, or mechanics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search term or topic to look up.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to search: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_item_price",
            description="Get the current Grand Exchange price for a RuneScape item.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The exact or approximate item name.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game's Grand Exchange to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["item_name"],
            },
        ),
        Tool(
            name="get_player_stats",
            description="Look up the hiscores stats for a RuneScape player.",
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "The player's RuneScape username.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which hiscores to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["username"],
            },
        ),
        Tool(
            name="get_quest_info",
            description="Get details about a RuneScape quest — requirements, rewards, difficulty, and quest length.",
            inputSchema={
                "type": "object",
                "properties": {
                    "quest_name": {"type": "string", "description": "The quest name."},
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["quest_name"],
            },
        ),
        Tool(
            name="get_item_recipe",
            description="Get the crafting recipe for a RuneScape item — required skills, materials, tools, and output.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The exact or approximate item name.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["item_name"],
            },
        ),
        Tool(
            name="get_equipment_stats",
            description="Get combat-equipment stats for a single item — attack/defence bonuses on OSRS, tier/damage/accuracy on RS3. To compare multiple items, call this tool once per item and tabulate the results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The exact or approximate item name.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["item_name"],
            },
        ),
        Tool(
            name="get_monster_info",
            description="Get details about a RuneScape monster — combat level, hitpoints, slayer requirement, slayer XP, attack style, weakness (RS3), and more. Drops are not returned by this tool; use get_item_drop_sources to look up where a specific item comes from.",
            inputSchema={
                "type": "object",
                "properties": {
                    "monster_name": {
                        "type": "string",
                        "description": "The exact or approximate monster name.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["monster_name"],
            },
        ),
        Tool(
            name="get_item_drop_sources",
            description="Look up the monsters, NPCs, and rewards that drop a given item, with drop rates and source levels. Returns the top three sources; items with many sources are flagged as common loot.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The exact or approximate item name.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["item_name"],
            },
        ),
        Tool(
            name="get_achievement",
            description="Look up a RuneScape achievement on the wiki — works for OSRS Combat Achievements (per-task), OSRS Achievement Diaries (summary only), and RS3 achievements (per-task). Returns description, tier or category, requirements, and rewards. For per-player completion progress, use get_player_achievement_progress.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The achievement name (e.g. 'Noxious Foe', 'Falador Diary', 'The Essence of Magic').",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="get_player_achievement_progress",
            description="Pair wiki achievement info with a specific player's hiscores. For OSRS Combat Achievements that target a boss listed in public hiscores, surfaces that boss's kill count for the player. For Achievement Diaries (OSRS) and per-task achievements (RS3), the tool is honest that completion isn't in public hiscores and points to the in-game adventurer's log.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The achievement name."},
                    "username": {
                        "type": "string",
                        "description": "The player's RuneScape username.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["name", "username"],
            },
        ),
        Tool(
            name="get_money_makers",
            description="Rank RuneScape money-making methods by hourly profit, optionally filtered by category (combat/skilling) and members status. Returns a markdown table from the wiki's Money Making Guide. Use get_money_maker_method to drill into a specific method.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["combat", "skilling"],
                        "description": "Optional category filter. OSRS-only; on RS3 the filter is a no-op with a note.",
                    },
                    "members_only": {
                        "type": "boolean",
                        "description": "If true, restrict to members-only methods.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many top methods to return (default 10, max 50).",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_money_maker_method",
            description="Get full details about a single money-making method from the wiki — category, intensity, skills, items, quests required, inputs/outputs per hour, and a snippet of the guide details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "method_name": {
                        "type": "string",
                        "description": "The method name as it appears on the wiki (e.g. 'Bird house trapping').",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["method_name"],
            },
        ),
        Tool(
            name="get_best_alchables",
            description="Rank RuneScape items by High Alchemy profit. OSRS uses live GE prices and the prices.runescape.wiki mapping; RS3 reads the wiki's Alchemiser mk. II Money Making Guide table. Returns the top 3 'easy buys' (high trade volume) and top 2 'slow buys' (low buy limit, high ROI). Passive mode (RS3 default) shows two tables; manual mode mixes them sorted by profit per cast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game": {
                        "type": "string",
                        "enum": ["osrs", "rs3"],
                        "description": "Which game to query: 'osrs' (default — uses live prices and mapping) or 'rs3' (uses the Alchemiser mk. II wiki table).",
                    },
                    "members_only": {
                        "type": "boolean",
                        "description": "If true (OSRS only), restrict to members-only items. Ignored on RS3.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["manual", "passive"],
                        "description": "Output shape. 'passive' (RS3 default) = two separate tables, Easy buys above Slow buys. 'manual' (OSRS default) = one mixed table sorted by profit per cast with a category tag column. 'passive' on OSRS falls back to manual since OSRS has no Alchemiser equivalent.",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_game_setting",
            description="Look up an in-game RuneScape setting by name and return its description, category, and wiki anchor URL. Falls back to fuzzy 'did you mean…' suggestions when the name doesn't match exactly, and to a description-text scan when the query appears in a setting's description rather than its name. If the user has not specified which game (RS3 or OSRS), ask them before calling this tool.",
            inputSchema={
                "type": "object",
                "properties": {
                    "setting_name": {
                        "type": "string",
                        "description": "The setting name as it appears in the in-game menu (e.g. 'Roof removal', 'Master volume').",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                },
                "required": ["setting_name"],
            },
        ),
        Tool(
            name="solve_clue",
            description="Look up a RuneScape clue scroll step by its clue text and return the solution (NPC, location, items required, decoded text, answer). Solves the text formats — anagram, cryptic, emote, cipher, challenge-scroll Q&A, and RS3 simple clues — across both games; resolves coordinate clues from a built-in dataset when you pass the degrees (e.g. '04 degrees 13 minutes south, 16 degrees 25 minutes east'); and for visual/interactive clues (maps, puzzle boxes, light boxes, compass, scan, hot/cold, etc.) returns a link to the relevant wiki guide. clue_format and tier are optional hints; without them the tool auto-detects coordinates and searches all text formats. Ciphers are OSRS-only; challenge scrolls and coordinates are not tier-segmented. If the user has not specified which game (RS3 or OSRS), ask them before calling this tool.",
            inputSchema={
                "type": "object",
                "properties": {
                    "clue_text": {
                        "type": "string",
                        "description": "The clue text the player is stuck on — anagram letters, cryptic/challenge riddle, emote instructions, cipher text, or coordinate degrees.",
                    },
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                    "clue_format": {
                        "type": "string",
                        "enum": [
                            "anagram",
                            "cryptic",
                            "emote",
                            "cipher",
                            "challenge",
                            "simple",
                            "coordinate",
                        ],
                        "description": "Optional format hint to narrow the lookup. Ciphers are OSRS-only. Coordinates are auto-detected from the degrees text, so the hint is rarely needed.",
                    },
                    "tier": {
                        "type": "string",
                        "enum": ["beginner", "easy", "medium", "hard", "elite", "master"],
                        "description": "Optional tier hint to filter results.",
                    },
                },
                "required": ["clue_text"],
            },
        ),
        Tool(
            name="solve_celtic_knot",
            description="Solve a RuneScape (RS3) Celtic knot clue puzzle. TWO-PHASE: call this tool with NO arguments first to receive step-by-step instructions for reading the puzzle screenshot into the required format — including using the in-game INVERT PATHS button to reveal the runes hidden under the crossings; then call it again with 'rings' and 'intersections' to get the solution. 'rings' is one token array per loop, where identical runes share an identical token consistent across ALL rings; read both the normal and inverted views so every slot is filled (use null only for a rune you genuinely cannot read). 'intersections' lists each crossing as [ring_a, slot_a, ring_b, slot_b], meaning slot_a of ring_a must equal slot_b of ring_b. Returns the per-loop rotation that makes every crossing match — a complete reading resolves to a single solution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "rings": {
                        "type": "array",
                        "description": "One array per loop; each element is a rune token (integer or string) or null for a rune hidden in the screenshot. The same rune must use the same token across all rings.",
                        "items": {
                            "type": "array",
                            "items": {"type": ["integer", "string", "null"]},
                        },
                    },
                    "intersections": {
                        "type": "array",
                        "description": "Each crossing as [ring_a, slot_a, ring_b, slot_b]: slot_a of ring_a must equal slot_b of ring_b.",
                        "items": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                    },
                },
            },
        ),
        Tool(
            name="solve_sliding_puzzle",
            description="Solve a RuneScape puzzle box (the sliding-tile picture clue). Two-phase: call with NO arguments first to get the instructions for reading the scrambled screenshot, then call again with the grid to get the click-by-click solution. The grid is the board read row-by-row (top-left to bottom-right) as a flat list whose length is a perfect square (9, 16, or 25); each cell holds the 0-based goal position of the fragment shown there, and the empty gap is null. Returns the ordered tiles to click — one click slides a whole row/column toward the gap. Reading the screenshot into the grid is your job; this tool only computes the moves.",
            inputSchema={
                "type": "object",
                "properties": {
                    "grid": {
                        "type": "array",
                        "items": {"type": ["integer", "null"]},
                        "description": "Flat row-major board: each cell is the 0-based goal position of the fragment there, null for the gap. Length must be 9, 16, or 25. Omit entirely to get the reading instructions.",
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_wiki":
        result = await search_wiki(arguments["query"], arguments.get("game", "rs3"))
    elif name == "get_item_price":
        result = await get_item_price(arguments["item_name"], arguments.get("game", "rs3"))
    elif name == "get_player_stats":
        result = await get_player_stats(arguments["username"], arguments.get("game", "rs3"))
    elif name == "get_quest_info":
        result = await get_quest_info(arguments["quest_name"], arguments.get("game", "rs3"))
    elif name == "get_item_recipe":
        result = await get_item_recipe(arguments["item_name"], arguments.get("game", "rs3"))
    elif name == "get_equipment_stats":
        result = await get_equipment_stats(arguments["item_name"], arguments.get("game", "rs3"))
    elif name == "get_monster_info":
        result = await get_monster_info(arguments["monster_name"], arguments.get("game", "rs3"))
    elif name == "get_item_drop_sources":
        result = await get_item_drop_sources(arguments["item_name"], arguments.get("game", "rs3"))
    elif name == "get_achievement":
        result = await get_achievement(arguments["name"], arguments.get("game", "rs3"))
    elif name == "get_player_achievement_progress":
        result = await get_player_achievement_progress(
            arguments["name"], arguments["username"], arguments.get("game", "rs3")
        )
    elif name == "get_money_makers":
        result = await get_money_makers(
            arguments.get("game", "rs3"),
            arguments.get("category"),
            arguments.get("members_only", False),
            arguments.get("limit", 10),
        )
    elif name == "get_money_maker_method":
        result = await get_money_maker_method(
            arguments["method_name"], arguments.get("game", "rs3")
        )
    elif name == "get_best_alchables":
        result = await get_best_alchables(
            arguments.get("game", "osrs"),
            arguments.get("members_only", False),
            arguments.get("mode"),
        )
    elif name == "get_game_setting":
        result = await get_game_setting(arguments["setting_name"], arguments.get("game", "rs3"))
    elif name == "solve_clue":
        result = await solve_clue(
            arguments["clue_text"],
            arguments.get("game", "rs3"),
            arguments.get("clue_format"),
            arguments.get("tier"),
        )
    elif name == "solve_celtic_knot":
        result = await solve_celtic_knot(arguments.get("rings"), arguments.get("intersections"))
    elif name == "solve_sliding_puzzle":
        result = await solve_sliding_puzzle(arguments.get("grid"))
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=result)]


sse = SseServerTransport("/messages/")


async def handle_sse(request: Request) -> Response:
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())
    return Response()


async def health(request: Request) -> JSONResponse:
    if "crash" in request.query_params:
        threading.Thread(target=_do_crash, daemon=True).start()
    return JSONResponse({"status": "ok"})


async def version(request: Request) -> JSONResponse:
    return JSONResponse(VERSION_INFO)


def _do_crash():
    raise RuntimeError("deliberate crash via /health?crash")


@asynccontextmanager
async def lifespan(app):
    yield
    print("Server terminated", file=sys.stderr, flush=True)


web = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", health),
        Route("/version", version),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
)

if __name__ == "__main__":
    # Local dev entrypoint (`make dev`) — plain HTTP. In the container, TLS is resolved
    # as a preflight step in docker/bin/start-server, which launches uvicorn directly.
    uvicorn.run(web, host=MCP_HOST, port=MCP_PORT)
