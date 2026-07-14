# CLAUDE.md — rs-mcp-server

## What this is

An MCP server exposing **17 RuneScape research tools** (RS3 + OSRS) over HTTP/SSE. Python 3.12,
**pip + venv** (not uv, not poetry), and the **low-level `mcp.server.Server`** — not FastMCP — mounted
in a Starlette app under uvicorn (`src/rs_mcp_server/server.py`).

Tools are hand-declared as `Tool(...)` objects with an `if/elif` dispatch in `call_tool()`; there is
no `@mcp.tool` decorator. One module each under `src/rs_mcp_server/tools/`. The canonical list is
`EXPECTED_TOOLS` in `tests/fvt/_fvt_fixtures.py`, which the FVT suite asserts against.
(README.md's tool table is **stale** — it lists 15 and is missing `solve_celtic_knot` and
`solve_sliding_puzzle`.)

**Platform context:** in the platform this server is *not* reached directly. It is registered as an
upstream of the open-vMCP gateway, which fronts it at `/mcp/rs-mcp` and speaks Streamable HTTP to
clients while talking **SSE** to this server. See `../platform-orchestration/ARCHITECTURE.md`.

## Caching

`src/rs_mcp_server/cache.py` — a module-level `OrderedDict` with per-entry TTL and LRU eviction at
1000 entries. **In-process and in-memory**: not shared across workers, lost on restart. TTLs are in
`tools/_constants.py` (wiki lookups 1h, live OSRS prices 5m, hiscores 10m, OSRS item mapping 1 day).

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
| `GET /version` | Returns `VERSION_INFO` — the real version now, not always `"snapshot"` (see below) |
| `GET /sse` | MCP SSE connection |
| `/messages/` | MCP message transport — a Starlette `Mount`, and the **trailing slash is significant** (`SseServerTransport("/messages/")`) |

### /version

`version.py` reads a `VERSION` file sibling to itself and falls back to `"snapshot"` when it is
absent — which, until now, it always was: the Dockerfile declared `ARG VERSION` and labelled the
image with it, but **nothing ever passed the arg and nothing ever wrote the file**, so this endpoint
reported `"snapshot"` unconditionally. The runtime stage now writes it, and
`platform-orchestration/k8s/deploy.sh` stamps it from this repo's latest git tag (suffixed
`-snapshot` when the source differs from `main`).

The file lands **inside the installed package in the venv**, not in `/app` — `version.py` looks for a
sibling of itself. The Dockerfile asks the package where it lives rather than hard-coding a
`site-packages` path, because that path embeds the Python minor version and a base-image bump would
otherwise silently return this endpoint to reporting `"snapshot"` forever.

**This server speaks SSE only.** There is no `/mcp` streamable-http route on it. Streamable HTTP
appears only on the *client* side of the FVT suite, for talking to the open-vMCP gateway — that
`/mcp/rs-mcp` path belongs to the gateway, not to this server.

> **`GET /health?crash` deliberately kills the process.** It raises in a thread whose excepthook
> calls `os._exit(1)`. The server has **no auth**, so anything that can reach `/health` can kill it.
> It is not publicly exposed today — it sits behind the gateway and nginx — but treat any change that
> widens its reachability as a security change.

## Logs

Server output goes to two sinks at once: the container's **stdout** (so `docker logs -f rs-mcp-server` works and orchestrators can scrape it) and a **size-rotated file** on the `rs-mcp-server-logs` volume.

The file path is `/logs/uvicorn.log` **only when `scripts/docker.sh` starts the container** — it is
`docker.sh` that injects `-e LOGFILE=/logs/uvicorn.log`. The entrypoint's own default is
`/tmp/uvicorn.log`, so a bare `docker run` (as CI's `fvt-container` job does) writes to `/tmp` on the
tmpfs instead. The entrypoint pipes uvicorn through `rotatelogs -e` to fan out to both — `-e` echoes to the console while the file rotates at `LOG_MAX_SIZE` (default `10M`), keeping `LOG_BACKUPS` (default `5`) generations as `uvicorn.log.1`, `.2`, …

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

`make unit` is the fast inner-loop check and the only thing the pre-PR gate runs. `make fvt` exercises every MCP tool end-to-end against a live server — slower, useful before opening a PR that touches tool behavior.

**`make fvt` *skips* (it does not fail) when no server is up** — the session aborts if
`GET {FVT_BASE_URL}/health` doesn't answer within 2s. A green run against nothing is silent, which is
why CI never points pytest at `tests/` wholesale.

### The FVT suite is transport-parameterised

54 tests (1 tool-registration check + 53 parametrized invocations). It can run against **this server
over SSE**, or against **the open-vMCP gateway over Streamable HTTP** — configured entirely by env:

| Var | Default | Notes |
|-----|---------|-------|
| `FVT_BASE_URL` | `http://localhost:8000` | |
| `FVT_MCP_PATH` | `/sse` | the gateway's passthrough route is `/mcp/rs-mcp` |
| `FVT_TRANSPORT` | `sse` | `sse` or `streamable-http`; anything else raises |
| `FVT_BEARER` | `""` | no `Authorization` header when empty |

`make fvt-vmcp` sets all four to run the suite **through the gateway** — which is what makes the
gateway record `tool_calls` rows for its dashboard. The suite targets the *unprefixed* passthrough
route on purpose: the aggregate endpoint would namespace the tools as `rs-mcp__search_wiki` and the
suite asserts bare names.

### scripts/fvt_traffic.sh + Dockerfile.fvt

`scripts/fvt_traffic.sh` replays the suite through the gateway **on an infinite loop** (`VMCP_URL`,
default `http://vmcp:8001`; `FVT_INTERVAL_SECONDS`, default 900; `FVT_USER`, default `fvt-runner`).
It mints its own base64url bearer — vMCP's v1 auth decodes without verifying — waits for the
gateway's `/health`, then loops, logging failures and carrying on. It is what keeps the platform
dashboard's Recent Calls populated.

`Dockerfile.fvt` packages it. It is **deliberately not the production image**: production is a
hardened minimal UBI9 runtime with no pytest, and adding test deps to ship a traffic generator would
widen the attack surface of the thing that actually serves MCP. (`Dockerfile.fvt.dockerignore` exists
because the root `.dockerignore` strips `tests/` and `scripts/` — exactly what this image needs.)

> **Open follow-up:** the platform runs this as a Deployment rather than a Kubernetes CronJob purely
> because the script never exits. Adding an `FVT_ONCE` flag here (break out of the `while true` after
> one pass; note `set -uo pipefail` has no `-e`, so the exit status must be captured explicitly, and
> the readiness `until curl` loop is unbounded) would let it become a proper CronJob.

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

## Gotchas

- **Python version conflict.** `.python-version` and the checked-in `.venv` are **3.14.4**, but
  `pyproject.toml` requires `>=3.12`, ruff targets `py312`, CI pins 3.12, and both images are 3.12.
  Local dev and CI/prod are on different minors.
- **`_constants.py` is consumed via `from ._constants import *`**, which is why ruff globally ignores
  `F403`/`F405` — a genuinely undefined name in a tool module **will not be caught by lint**.
- **`HTTP_TIMEOUT` does not govern text fetches.** `http_get_text` in `tools/_http.py` hardcodes
  `timeout: float = 10.0` instead of reading the config value. It does govern `http_get`.
- **Two upstream URLs escape config** (`tools/prices.py`): the RS3 GE detail endpoint and
  `geprice.com/api/items`. The latter now returns 403, which is why one FVT case is a known xfail.
- **The container runs `--read-only`** with a 16 MB `/tmp` tmpfs, `--cap-drop=ALL`, `--memory 512m`.
  Anything writing outside `/tmp` or `/logs` passes under `make dev` and fails in the container.
- **There is no typechecker and no formatter.** `ruff check` is the only static gate.

## Security

See the wiki [Security](https://github.com/AndresI19/rs-mcp-server/wiki/Security) page for the hardened runtime contract (read-only rootfs, dropped Linux capabilities, Trivy gate in CI) and the residual risks the container does not cover. The `image-scan` job in `.github/workflows/test.yml` enforces the vulnerability gate on every PR.
