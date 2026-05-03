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
    uvicorn.run(web, host="0.0.0.0", port=8000)
