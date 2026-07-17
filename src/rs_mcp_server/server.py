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
from rs_mcp_server.tools import REGISTRY
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

# Each tool's schema AND dispatch live on its ToolSpec (see tools/_registry.py); importing the
# tools package populated REGISTRY. list_tools() renders it; call_tool() dispatches by name.
_TOOLS_BY_NAME = {spec.name: spec for spec in REGISTRY}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [spec.tool for spec in REGISTRY]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    spec = _TOOLS_BY_NAME.get(name)
    if spec is None:
        raise ValueError(f"Unknown tool: {name}")
    result = await spec.invoke(arguments)
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
