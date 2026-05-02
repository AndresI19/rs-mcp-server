# rs-mcp-server

RuneScape research tools exposed to Claude Desktop via the [Model Context Protocol](https://modelcontextprotocol.io).

## Tools

| Tool | Description |
|------|-------------|
| `search_wiki` | Search the RuneScape Wiki for items, quests, skills, monsters, or mechanics |
| `get_item_price` | Look up the current Grand Exchange price for an item |
| `get_player_stats` | Retrieve hiscores stats for a player |
| `get_quest_info` | Get quest requirements, rewards, and walkthrough |

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
make start   # opens a log window, polls health, prints the SSE endpoint
make stop    # kill the server
make logs    # tail /tmp/mcp-server.log
```

Starts on `http://0.0.0.0:8000`. Endpoints:

| Path | Description |
|------|-------------|
| `GET /health` | Returns `{"status": "ok"}` — liveness check |
| `GET /sse` | MCP SSE connection endpoint (Claude Desktop connects here) |
| `POST /messages` | MCP message endpoint (used by SSE transport) |

## Verification

```bash
make smoke-test   # exercise all tools over SSE end-to-end (server must be running)
```

Asserts each tool returns the expected structured output for representative inputs. Exits 0 on success, 1 on any failure.

## Project layout

```
server.py       — MCP app: registers tools, dispatches calls
cache.py        — in-memory TTL cache shared across all tools
tools/
  wiki.py       — search_wiki (RS3 Wiki MediaWiki API)
  prices.py     — get_item_price (RS3 Grand Exchange API)
  hiscores.py   — get_player_stats, get_quest_info
```
