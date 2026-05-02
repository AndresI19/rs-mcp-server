# CLAUDE.md — rs-mcp-server

## Server lifecycle

| Action | Command |
|--------|---------|
| Start (opens log window for user) | `make start` |
| Stop | `make stop` |
| Tail logs live | `make logs` |
| Check if running | `curl -sf http://localhost:8000/health` |
| Smoke test all tools over SSE | `make smoke-test` |

`make start` opens a Ptyxis terminal window so the user can see live logs, polls the health endpoint, then prints the MCP endpoint URL and the exact stop command. Always use `make start` rather than invoking uvicorn directly.

## Endpoints

| Path | Purpose |
|------|---------|
| `GET /health` | Liveness check — returns `{"status": "ok"}` |
| `GET /sse` | MCP SSE connection (Claude Desktop connects here) |
| `POST /messages` | MCP message transport |

## Log file

Logs are written to `/tmp/mcp-server.log` while the server is running.
