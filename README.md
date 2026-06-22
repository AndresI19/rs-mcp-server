# rs-mcp-server

RuneScape research tools exposed to AI agents over the [Model Context Protocol](https://modelcontextprotocol.io) — wiki lookups, Grand Exchange prices, hiscores, drops, money-making, clues, and more. Serves both Old School (OSRS) and RuneScape 3 (RS3) data from public APIs, with no authentication required.

## Tools

| Tool | Description |
|------|-------------|
| `search_wiki` | Search the RuneScape Wiki for items, quests, skills, monsters, or mechanics |
| `get_item_price` | Current Grand Exchange price for an item |
| `get_player_stats` | A player's hiscores skill levels and activity/boss rankings |
| `get_quest_info` | Quest requirements, rewards, difficulty, and length |
| `get_item_recipe` | Crafting recipe for an item — skills, materials, and outputs |
| `get_equipment_stats` | Combat bonuses plus set-bonus and passive effects for equipment |
| `get_monster_info` | Combat stats and Slayer info for a monster |
| `get_item_drop_sources` | Which monsters drop an item, ranked by rarity |
| `get_achievement` | Achievement, Combat Achievement, or Diary infobox details |
| `get_player_achievement_progress` | An achievement paired with a player's related hiscores progress |
| `get_money_makers` | Money-making methods ranked by hourly profit |
| `get_money_maker_method` | Full detail for a single money-making method |
| `get_best_alchables` | Items ranked by High Alchemy profit |
| `get_game_setting` | What an in-game setting does, from the wiki Settings page |
| `solve_clue` | Solve a Treasure Trail clue (anagram, cryptic, emote, or cipher) |

## Run & connect

Start the server in a container (Linux needs Colima running first — `colima start`):

```bash
make start          # build image, run container, poll /health — serves on :8000
make stop           # remove the container
make logs           # tail the server log
```

To serve on a different host port, set `PORT` — the container always listens on 8000 internally and this remaps the host side:

```bash
PORT=9000 make start     # → http://localhost:9000/sse
```

With the server running, point an MCP client at `http://localhost:8000/sse` (or your `PORT`):

- **Claude Code** — this repo ships a project-scoped [`.mcp.json`](.mcp.json) that registers the server automatically when the repo is your project. Equivalent CLI: `claude mcp add --transport sse rs-mcp http://localhost:8000/sse` (add `--scope user` to register it for every project).
- **Claude Desktop** — its config has no native SSE entry, so bridge through `mcp-remote`:
  ```json
  { "mcpServers": { "rs-mcp": { "command": "npx", "args": ["mcp-remote@^0.1.38", "http://localhost:8000/sse"] } } }
  ```
- **claude.ai Connectors** (Linux/web) — paste the SSE URL directly. When serving TLS use `https://`; for a deployed server swap `localhost:<port>` for the public host.

---

**Full documentation** — development, container & deployment, security, testing & CI, and architecture — lives in the [project wiki](https://github.com/AndresI19/rs-mcp-server/wiki).
