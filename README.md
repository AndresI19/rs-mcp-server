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

## Run (stdio mode for Claude Desktop)

```bash
python server.py
```

## Project layout

```
server.py       — MCP app: registers tools, dispatches calls
cache.py        — in-memory TTL cache shared across all tools
tools/
  wiki.py       — search_wiki (RS3 Wiki MediaWiki API)
  prices.py     — get_item_price (RS3 Grand Exchange API)
  hiscores.py   — get_player_stats, get_quest_info
```
