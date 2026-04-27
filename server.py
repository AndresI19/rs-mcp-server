"""RuneScape MCP Server — HTTP/SSE entry point."""
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from tools.wiki import search_wiki
from tools.prices import get_item_price
from tools.hiscores import get_player_stats, get_quest_info

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
                    "item_name": {"type": "string", "description": "The exact or approximate item name."}
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
                    "username": {"type": "string", "description": "The player's RuneScape username."}
                },
                "required": ["username"],
            },
        ),
        Tool(
            name="get_quest_info",
            description="Get details about a RuneScape quest — requirements, rewards, and walkthrough.",
            inputSchema={
                "type": "object",
                "properties": {
                    "quest_name": {"type": "string", "description": "The quest name."}
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
        result = await get_item_price(arguments["item_name"])
    elif name == "get_player_stats":
        result = await get_player_stats(arguments["username"])
    elif name == "get_quest_info":
        result = await get_quest_info(arguments["quest_name"])
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=result)]


sse = SseServerTransport("/messages")


async def handle_sse(scope, receive, send):
    async with sse.connect_sse(scope, receive, send) as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


web = Starlette(
    routes=[
        Route("/health", health),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse.handle_post_message),
    ]
)

if __name__ == "__main__":
    uvicorn.run(web, host="0.0.0.0", port=8000)
