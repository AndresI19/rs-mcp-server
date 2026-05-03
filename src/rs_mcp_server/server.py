"""RuneScape MCP Server — HTTP/SSE entry point."""
import os
import sys
import threading
import traceback
from contextlib import asynccontextmanager
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from rs_mcp_server.logging import setup_logging
from rs_mcp_server.tools.wiki import search_wiki
from rs_mcp_server.tools.prices import get_item_price
from rs_mcp_server.tools.hiscores import get_player_stats
from rs_mcp_server.tools.quests import get_quest_info
from rs_mcp_server.tools.recipes import get_item_recipe
from rs_mcp_server.tools.equipment import get_equipment_stats
from rs_mcp_server.tools.moneymakers import get_money_makers, get_money_maker_method
from rs_mcp_server.tools.settings import get_game_setting
from rs_mcp_server.tools.clues import solve_clue

setup_logging()


def _excepthook(exc_type, exc_value, exc_tb):
    frames = "".join(traceback.format_tb(exc_tb, limit=3))
    print(f"\nServer terminated — {exc_type.__name__}: {exc_value}\n{frames}", file=sys.stderr, flush=True)


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
                    "query": {"type": "string", "description": "The search term or topic to look up."},
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
                    "item_name": {"type": "string", "description": "The exact or approximate item name."},
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
                    "username": {"type": "string", "description": "The player's RuneScape username."},
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
                    "item_name": {"type": "string", "description": "The exact or approximate item name."},
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
                    "item_name": {"type": "string", "description": "The exact or approximate item name."},
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
                    "method_name": {"type": "string", "description": "The method name as it appears on the wiki (e.g. 'Bird house trapping')."},
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
            name="get_game_setting",
            description="Look up an in-game RuneScape setting by name and return its description, category, and wiki anchor URL. Falls back to fuzzy 'did you mean…' suggestions when the name doesn't match exactly, and to a description-text scan when the query appears in a setting's description rather than its name. If the user has not specified which game (RS3 or OSRS), ask them before calling this tool.",
            inputSchema={
                "type": "object",
                "properties": {
                    "setting_name": {"type": "string", "description": "The setting name as it appears in the in-game menu (e.g. 'Roof removal', 'Master volume')."},
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
            description="Look up a RuneScape clue scroll step by its clue text and return the solution (NPC, location, items required, decoded text). Supports four text-based clue formats — anagrams, cryptics, emotes, and ciphers — across both games. Provide clue_format and tier as optional hints to narrow the search and reduce cold-cache fetches; without them, the tool searches all loaded formats. Ciphers are OSRS-only. If the user has not specified which game (RS3 or OSRS), ask them before calling this tool.",
            inputSchema={
                "type": "object",
                "properties": {
                    "clue_text": {"type": "string", "description": "The clue text the player is stuck on (anagram letters, cryptic riddle, emote instructions, or cipher text)."},
                    "game": {
                        "type": "string",
                        "enum": ["rs3", "osrs"],
                        "description": "Which game wiki to query: 'rs3' (default) or 'osrs'.",
                    },
                    "clue_format": {
                        "type": "string",
                        "enum": ["anagram", "cryptic", "emote", "cipher"],
                        "description": "Optional format hint to narrow the lookup. Ciphers are OSRS-only.",
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
    elif name == "get_money_makers":
        result = await get_money_makers(
            arguments.get("game", "rs3"),
            arguments.get("category"),
            arguments.get("members_only", False),
            arguments.get("limit", 10),
        )
    elif name == "get_money_maker_method":
        result = await get_money_maker_method(arguments["method_name"], arguments.get("game", "rs3"))
    elif name == "get_game_setting":
        result = await get_game_setting(arguments["setting_name"], arguments.get("game", "rs3"))
    elif name == "solve_clue":
        result = await solve_clue(
            arguments["clue_text"],
            arguments.get("game", "rs3"),
            arguments.get("clue_format"),
            arguments.get("tier"),
        )
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
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ]
)

if __name__ == "__main__":
    uvicorn.run(web, host=os.environ.get("MCP_HOST", "127.0.0.1"), port=8000)
