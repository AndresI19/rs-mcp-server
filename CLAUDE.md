# CLAUDE.md — rs-mcp-server

## Server lifecycle

| Action | Command |
|--------|---------|
| Start (build image + run container) | `make start` |
| Stop (remove container) | `make stop` |
| Tail logs live | `make logs` |
| Check if running | `curl -sf http://localhost:8000/health` |
| Run FVT against the live server | `make fvt` |
| Clean (image + volume + dangling layers) | `bash scripts/docker.sh clean` |

`make start` checks the Docker daemon (instructs `colima start` on Linux if down), builds the `rs-mcp-server:dev` image, starts a detached container on port 8000, and polls `/health` until ready. `make dev` is preserved for in-venv iteration without Docker.

The container binds to `0.0.0.0:8000` internally; the host sees it on `localhost:8000` via `-p 8000:8000`. Production deploys swap the run flags but keep the image identical.

### TLS

TLS is opt-in via a mounted cert directory — a preflight step in the container entrypoint (`docker/bin/start-server`) resolves the listener mode from `/etc/tls_certs` before the server process starts, then launches uvicorn with the matching `--ssl-*` flags:

| Cert dir | Listener |
|----------|----------|
| Not mounted | Plain HTTP (default) |
| Mounted, empty / no usable pair | HTTPS with a self-signed fallback cert |
| Mounted with `tls.crt`+`tls.key` (or `fullchain.pem`+`privkey.pem`, or `cert.pem`+`key.pem`) | HTTPS with those certs |

Run with TLS locally: `TLS_CERTS_DIR=/path/to/certs make start` (mounts the dir read-only at `/etc/tls_certs` and polls health over https). The same port `8000` carries HTTP or HTTPS — there is no second port. `make dev` (local venv, no container) is always plain HTTP, since the TLS preflight lives in the container entrypoint. Full rationale in the wiki [Security › Transport security (TLS)](https://github.com/AndresI19/rs-mcp-server/wiki/Security#transport-security-tls).

## Configuration

Every variable is optional — the server runs with an empty environment — and all of them are
resolved and validated once, on import, in `src/rs_mcp_server/config.py`. A value that is *set and
wrong* fails at boot naming the variable, instead of surfacing later as a confusing timeout or a 404
from an endpoint nobody realised was hardcoded.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_HOST` | `127.0.0.1` | Listen address. The container sets `0.0.0.0` explicitly — a dev server that binds every interface the moment you run it is a surprise, not a convenience. |
| `MCP_PORT` | `8000` | Listen port. |
| `HTTP_TIMEOUT` | `10.0` | Per-request timeout, seconds, for outbound calls to the wikis/APIs. |
| `HTTP_MAX_RETRIES` | `2` | Retries for transient upstream failures (429/502/503/504). `0` disables. |
| `USER_AGENT` | `RS-MCP-Server/<version>` | The wikis ask that tools identify themselves. Override to add a contact: `RS-MCP-Server/1.2 (+https://example.com/contact)`. |
| `RS3_WIKI_API` / `OSRS_WIKI_API` | the two `api.php` endpoints | MediaWiki API per game. |
| `RS3_WIKI_BASE` / `OSRS_WIKI_BASE` | the two `/w/` prefixes | Used to build the article links in tool output. |
| `OSRS_PRICES_BASE` | `https://prices.runescape.wiki/api/v1/osrs` | Live GE price API. |
| `RS3_HISCORES_URL` / `OSRS_HISCORES_URL` | the two `index_lite.json` endpoints | Hiscores. Separate variables, not a shared base — they are different products behind different `m=` paths. |

The upstream endpoints are overridable so the server can be pointed at a mirror, a caching proxy, or
a fixture host without editing source.

## Endpoints

| Path | Purpose |
|------|---------|
| `GET /health` | Liveness check — returns `{"status": "ok"}` |
| `GET /sse` | MCP SSE connection (Claude Desktop connects here) |
| `POST /messages` | MCP message transport |

## Logs

Server output goes to two sinks at once: the container's **stdout** (so `docker logs -f rs-mcp-server` works and orchestrators can scrape it) and a **size-rotated file** at `/logs/uvicorn.log` on the `rs-mcp-server-logs` volume. The entrypoint pipes uvicorn through `rotatelogs -e` to fan out to both — `-e` echoes to the console while the file rotates at `LOG_MAX_SIZE` (default `10M`), keeping `LOG_BACKUPS` (default `5`) generations as `uvicorn.log.1`, `.2`, …

Tail the file with `make logs` (delegates to `scripts/docker.sh logs`); because it lives on the volume it survives container removal and can still be tailed after `make stop`. The current log is always at the stable path `/logs/uvicorn.log`, so `make logs` is unaffected by rotation.

## Pre-PR checks

These commands must pass before `/pr` opens a PR — the `/pr` skill runs them as Step 0 and aborts on any non-zero exit. Run from repo root:

```bash
.venv/bin/ruff check .
make unit
```

Note: pre-PR checks are unit-only on purpose — fast, no container, no live wiki/hiscores calls. `make fvt` is the slower function-verification suite (see Local development below).

## Local development

On Linux, Docker requires Colima as the container runtime:

```bash
colima start    # required before make start / make fvt
```

`make start` and `bash scripts/docker.sh start` both check the daemon and print the `colima start` hint if it's down.

The test suite is split into two tiers:

| Tier | Command | Speed | Requires container |
|------|---------|-------|--------------------|
| Unit | `make unit` | ~1s | No (runs in .venv) |
| Function-verification | `make fvt` | ~30s | Yes (must `make start` first) |

`make unit` is the fast inner-loop check and the only thing the pre-PR gate runs. `make fvt` exercises every MCP tool end-to-end over SSE against a live server — slower, useful before opening a PR that touches tool behavior.

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

## Security

See the wiki [Security](https://github.com/AndresI19/rs-mcp-server/wiki/Security) page for the hardened runtime contract (read-only rootfs, dropped Linux capabilities, Trivy gate in CI) and the residual risks the container does not cover. The `image-scan` job in `.github/workflows/test.yml` enforces the vulnerability gate on every PR.
