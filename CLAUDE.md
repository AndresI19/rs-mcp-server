# CLAUDE.md — rs-mcp-server

## Server lifecycle

| Action | Command |
|--------|---------|
| Start (opens log window for user) | `make start` |
| Stop | `make stop` |
| Tail logs live | `make logs` |
| Check if running | `curl -sf http://localhost:8000/health` |
| Smoke test all tools over SSE | `make smoke-test` |
| Bind to all interfaces (production) | `MCP_HOST=0.0.0.0 make start` |

`make start` opens a Ptyxis terminal window so the user can see live logs, polls the health endpoint, then prints the MCP endpoint URL and the exact stop command. Always use `make start` rather than invoking uvicorn directly.

The dev server binds to `127.0.0.1` by default — local dev is fine because Claude Desktop and `make smoke-test` connect via `localhost`. Production deployments must set `MCP_HOST=0.0.0.0` (or a specific public-interface address) so external clients can reach the server.

## Endpoints

| Path | Purpose |
|------|---------|
| `GET /health` | Liveness check — returns `{"status": "ok"}` |
| `GET /sse` | MCP SSE connection (Claude Desktop connects here) |
| `POST /messages` | MCP message transport |

## Log file

Logs are written to `/tmp/mcp-server.log` while the server is running.

## Pre-PR checks

These commands must pass before `/pr` opens a PR — the `/pr` skill runs them as Step 0 and aborts on any non-zero exit. Run from repo root:

```bash
.venv/bin/ruff check .
make test
```

## Dependency locking

`requirements.txt` (committed) is the locked, hash-verified runtime dep list, generated from `pyproject.toml` via `pip-tools`. The container build (Epic #62 / C2) consumes it with `pip install -r requirements.txt --require-hashes` so image layer hashes are stable across builds.

Regenerate after editing the `[project] dependencies` block in `pyproject.toml`:

```bash
make lock
```

The dev `.venv` itself uses `pip install -e .[test]` (loose constraints, editable install) — `requirements.txt` is for reproducibility downstream, not for daily dev iteration. To verify the lockfile installs cleanly in a fresh environment:

```bash
python3 -m venv /tmp/lock-verify
/tmp/lock-verify/bin/pip install -r requirements.txt --require-hashes
```
