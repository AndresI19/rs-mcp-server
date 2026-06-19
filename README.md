# rs-mcp-server

RuneScape research tools exposed to Claude Desktop via the [Model Context Protocol](https://modelcontextprotocol.io).

## Tools

| Tool | Description |
|------|-------------|
| `search_wiki` | Search the RuneScape Wiki for items, quests, skills, monsters, or mechanics |
| `get_item_price` | Look up the current Grand Exchange price for an item |
| `get_player_stats` | Retrieve hiscores stats for a player |
| `get_quest_info` | Get quest requirements, rewards, difficulty, and length |

## Setup

```bash
pip install -e ".[test]"
```

The `[test]` extra adds `pytest` and `ruff` for local development. Drop it for runtime-only installs.

## Run

```bash
make start   # checks Docker, builds image, runs container, polls /health
make stop    # removes the container
make logs    # tails the container log (via scripts/docker.sh)
```

`make dev` is preserved for in-venv iteration without Docker. On Linux, Colima must be running:

```bash
colima start
```

### Container build

`scripts/docker.sh` is the lifecycle wrapper that `make start` delegates to. You can also call its subcommands directly:

```bash
bash scripts/docker.sh start   # build image + run container detached on port 8000
bash scripts/docker.sh logs    # tail the container's uvicorn log
bash scripts/docker.sh stop    # docker rm -f
bash scripts/docker.sh clean   # remove container + volume + image + dangling layers
```

Image: `rs-mcp-server:dev`, built from the multi-stage `Dockerfile` in the repo root.

Starts on `http://localhost:8000`. Endpoints:

| Path | Description |
|------|-------------|
| `GET /health` | Returns `{"status": "ok"}` — liveness check |
| `GET /sse` | MCP SSE connection endpoint (Claude Desktop connects here) |
| `POST /messages` | MCP message endpoint (used by SSE transport) |

## Connect an MCP client

With the server running (`make start`), point a client at `http://localhost:8000/sse`.

**Claude Code** — this repo ships a project-scoped [`.mcp.json`](.mcp.json) that registers the server automatically when the repo is your Claude Code project:

```json
{
  "mcpServers": {
    "rs-mcp": { "type": "sse", "url": "http://localhost:8000/sse" }
  }
}
```

The same file is produced by `claude mcp add --transport sse rs-mcp http://localhost:8000/sse`. Add `--scope user` (instead of the default `--scope project`) to register it for every Claude Code project rather than just this repo.

**Claude Desktop** — its `claude_desktop_config.json` has no native SSE entry, so bridge through `mcp-remote`:

```json
{
  "mcpServers": {
    "rs-mcp": { "command": "npx", "args": ["mcp-remote@^0.1.38", "http://localhost:8000/sse"] }
  }
}
```

Claude Desktop is macOS/Windows only; on Linux use Claude Code or the claude.ai web **Connectors** UI, which accepts the SSE URL directly. When the server is serving TLS (see [docs/security.md](docs/security.md)) use `https://`, and for a deployed server swap `localhost:8000` for the public host.

## Verification

```bash
make fvt   # exercise every MCP tool over SSE end-to-end (server must be running)
```

Asserts each tool returns the expected structured output for representative inputs. Exits 0 on success, 1 on any failure.

## Continuous integration

`.github/workflows/test.yml` runs on every pull request and on every push to `main`:

| Job | Command | Purpose |
|-----|---------|---------|
| `lint-and-import` | `ruff check .` + import-only smoke | Lint and catch import-graph breaks |
| `pytest` | `pytest tests/ -v` | Full unit-test suite |

Both jobs are required status checks on `main` — a pull request cannot be merged until both pass *and* the branch is up to date with `main`.

## Project layout

```
pyproject.toml          — package definition, runtime + test dependencies
src/rs_mcp_server/
  __init__.py
  server.py             — MCP app: registers tools, dispatches calls
  cache.py              — in-memory TTL cache shared across all tools
  tools/
    __init__.py
    _http.py            — shared async HTTP helpers
    wiki.py             — search_wiki (RS3 / OSRS MediaWiki APIs)
    prices.py           — get_item_price (RS3 / OSRS Grand Exchange APIs)
    hiscores.py         — get_player_stats (Jagex Hiscores)
    quests.py           — get_quest_info (RS3 / OSRS wiki quest data)
tests/                  — pytest unit tests for parsing helpers
build/                  — reserved for future build artifacts
scripts/
  docker.sh             — container lifecycle (called by make start / stop / logs)
```
