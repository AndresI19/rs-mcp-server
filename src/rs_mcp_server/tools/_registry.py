"""The tool registry — one place a tool declares BOTH its MCP schema and how to invoke it.

Before this, `server.py` carried a ~360-line hand-written `list_tools()` schema block and a ~55-line
`call_tool()` `if/elif` dispatcher, so every tool's contract lived in two files far from the tool
itself. Now each tool module builds one `ToolSpec` and `register()`s it; `server.py` renders the tool
list and dispatches straight from `REGISTRY`. Adding or changing a tool is a single-module edit.

The `invoke` adapter is the deliberate join: it maps the MCP `arguments` dict to the handler's real
signature (positional args, per-tool defaults like game='rs3' vs 'osrs'), keeping that mapping WITH
the tool rather than in a central switch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp.types import Tool

#: Maps the validated MCP arguments dict to an awaitable of the tool's text result.
Invoke = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    """A tool's public contract: its schema plus the call that runs it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    invoke: Invoke

    @property
    def tool(self) -> Tool:
        return Tool(name=self.name, description=self.description, inputSchema=self.input_schema)


#: Populated at import time as each tool module is imported (see tools/__init__.py).
REGISTRY: list[ToolSpec] = []


def register(spec: ToolSpec) -> ToolSpec:
    """Append a tool to the registry and return it (so a module can `TOOL = register(ToolSpec(...))`)."""
    REGISTRY.append(spec)
    return spec


# ── Schema helpers ─────────────────────────────────────────────────────────────────────────────
# The `game` enum was written out ~15 times in the old list_tools(). Factor the STRUCTURE here; each
# tool still passes its own wording, because the descriptions are part of the tool's contract.


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def game_param(description: str, games: tuple[str, ...] = ("rs3", "osrs")) -> dict[str, Any]:
    return {"type": "string", "enum": list(games), "description": description}
