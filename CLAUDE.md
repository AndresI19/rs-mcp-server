# CLAUDE.md — rs-mcp-server

## What this is

An MCP server exposing **17 RuneScape research tools** (RS3 + OSRS) over HTTP/SSE. Python 3.12,
**pip + venv** (not uv/poetry), and the **low-level `mcp.server.Server`** — not FastMCP — mounted in a
Starlette app under uvicorn (`src/rs_mcp_server/server.py`).

Each tool module declares a **`ToolSpec`** (its MCP schema **and** dispatch mapping) and `register()`s it
into `REGISTRY` (`tools/_registry.py`); `server.py` renders `list_tools()` and dispatches `call_tool()`
straight from the registry — no `@mcp.tool` decorator, no central schema list or `if/elif`. One module each
under `src/rs_mcp_server/tools/`; the package `__init__.py` imports them in **tool-list order** (so it opts
out of import sorting). Adding a tool is a single-module edit. The canonical list is `EXPECTED_TOOLS` in
`tests/fvt/_fvt_fixtures.py`, which the FVT suite asserts against.

**Platform context:** this server is *not* reached directly. It is an upstream of the open-vMCP gateway,
which fronts it at `/mcp/rs-mcp`, speaking Streamable HTTP to clients but **SSE** to this server. See
`../platform-orchestration/ARCHITECTURE.md`.

## Caching

`src/rs_mcp_server/cache.py` — a module-level `OrderedDict` with per-entry TTL and LRU eviction at 1000
entries. **In-process, in-memory**: not shared across workers, lost on restart. TTLs are in
`tools/_constants.py` (wiki 1h, live OSRS prices 5m, hiscores 10m, OSRS item mapping 1 day).

## Server lifecycle

| Action | Command |
|--------|---------|
| Start (build image + run container) | `make start` |
| Stop (remove container) | `make stop` |
| Tail logs live | `make logs` |
| Check if running | `curl -sf http://localhost:8000/health` |
| Run FVT against the live server | `make fvt` |
| Clean (image + volume + dangling layers) | `bash scripts/docker.sh clean` |

`make start` checks the Docker daemon (hints `colima start` on Linux if down), builds `rs-mcp-server:dev`,
runs a detached container on port 8000, and polls `/health` until ready. `make dev` is in-venv iteration
without Docker. The container binds `0.0.0.0:8000` internally; the host sees `localhost:8000` via
`-p 8000:8000`. Production keeps the image identical, only swapping run flags.

### TLS

TLS is opt-in via a mounted cert directory. A preflight in the container entrypoint
(`docker/bin/start-server`) resolves the listener mode from `/etc/tls_certs` before uvicorn starts, then
launches it with matching `--ssl-*` flags:

| Cert dir | Listener |
|----------|----------|
| Not mounted | Plain HTTP (default) |
| Mounted, empty / no usable pair | HTTPS, self-signed fallback cert |
| Mounted with `tls.crt`+`tls.key` (or `fullchain.pem`+`privkey.pem`, or `cert.pem`+`key.pem`) | HTTPS with those certs |

Run TLS locally: `TLS_CERTS_DIR=/path/to/certs make start` (mounts read-only at `/etc/tls_certs`, polls
health over https). One port `8000` carries HTTP or HTTPS — no second port. `make dev` is always plain HTTP
(the TLS preflight lives in the container entrypoint). Full rationale: wiki [Security › Transport security
(TLS)](https://github.com/AndresI19/rs-mcp-server/wiki/Security#transport-security-tls).

## Configuration

Every variable is optional — the server runs with an empty environment — and all are resolved and validated
once, on import, in `src/rs_mcp_server/config.py`. A value that is *set and wrong* fails at boot naming the
variable, rather than surfacing later as a confusing timeout or a 404 from a hardcoded endpoint.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_HOST` | `127.0.0.1` | Listen address. The container sets `0.0.0.0` explicitly. |
| `MCP_PORT` | `8000` | Listen port. |
| `HTTP_TIMEOUT` | `10.0` | Per-request timeout (s) for outbound wiki/API calls. |
| `HTTP_MAX_RETRIES` | `2` | Retries for transient upstream failures (429/502/503/504); `0` disables. |
| `USER_AGENT` | `RS-MCP-Server/<version>` | Tool identity for the wikis. Override to add a contact. |
| `RS3_WIKI_API` / `OSRS_WIKI_API` | the two `api.php` endpoints | MediaWiki API per game. |
| `RS3_WIKI_BASE` / `OSRS_WIKI_BASE` | the two `/w/` prefixes | Build article links in tool output. |
| `OSRS_PRICES_BASE` | `https://prices.runescape.wiki/api/v1/osrs` | Live GE price API. |
| `RS3_GE_DETAIL_URL` | the RS3 `catalogue/detail.json` endpoint | RS3 item-price lookup. |
| `GEPRICE_CATALOG_URL` | `https://geprice.com/api/items` | Secondary GE catalogue. Returns 403 today (one FVT case xfails); overridable to point at a working mirror. |
| `RS3_HISCORES_URL` / `OSRS_HISCORES_URL` | the two `index_lite.json` endpoints | Hiscores. Separate vars, not a shared base — different products behind different `m=` paths. |

Endpoints are overridable so the server can be pointed at a mirror, caching proxy, or fixture host without
editing source.

## Endpoints

| Path | Purpose |
|------|---------|
| `GET /health` | Liveness — `{"status": "ok"}` |
| `GET /version` | Returns `VERSION_INFO` (see below) |
| `GET /sse` | MCP SSE connection |
| `/messages/` | MCP message transport — a Starlette `Mount`; the **trailing slash is significant** (`SseServerTransport("/messages/")`) |

### /version

`version.py` reads a `VERSION` file sibling to itself, falling back to `"snapshot"` when absent (dev
checkouts). The runtime image writes it; `platform-orchestration/k8s/deploy.sh` stamps it from the latest
git tag (suffixed `-snapshot` when the source differs from `main`). The file lands **inside the installed
package in the venv**, not `/app`. The Dockerfile asks the package where it lives rather than hard-coding a
`site-packages` path — that path embeds the Python minor version, so a base-image bump would otherwise
silently revert this endpoint to `"snapshot"` forever.

**This server speaks SSE only** — there is no `/mcp` streamable-http route on it. Streamable HTTP is
client-side only in the FVT suite, for the open-vMCP gateway; that `/mcp/rs-mcp` path belongs to the gateway.

> **`GET /health?crash` deliberately kills the process.** It raises in a thread whose excepthook calls
> `os._exit(1)`. The server has **no auth**, so anything that can reach `/health` can kill it. Not publicly
> exposed today (behind the gateway and nginx) — treat any change that widens its reachability as a security
> change.

## Logs

Server output goes to two sinks: the container's **stdout** (`docker logs -f`) and a **size-rotated file**
on the `rs-mcp-server-logs` volume.

The file path is `/logs/uvicorn.log` **only when `scripts/docker.sh` starts the container** — it injects
`-e LOGFILE=/logs/uvicorn.log`. The entrypoint's own default is `/tmp/uvicorn.log`, so a bare `docker run`
(CI's `fvt-container` job) writes to `/tmp` on the tmpfs. The entrypoint pipes uvicorn through `rotatelogs
-e` to fan out to both: `-e` echoes to console while the file rotates at `LOG_MAX_SIZE` (default `10M`),
keeping `LOG_BACKUPS` (default `5`) generations as `uvicorn.log.1`, `.2`, …

`make logs` tails the file (via `scripts/docker.sh logs`); it lives on the volume, so it survives container
removal and stays tailable after `make stop`. The current log is always `/logs/uvicorn.log`, so rotation
never affects `make logs`.

## Pre-PR checks

These must pass before `/pr` opens a PR — the `/pr` skill runs them as Step 0 and aborts on non-zero. From
repo root:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
make unit
```

CI enforces both `ruff check` (lint) and `ruff format --check` (formatting) in its `lint-and-import`
job, so a green PR needs both — running only the linter locally lets a formatting-only failure through.
Pre-PR checks are unit-only on purpose — fast, no container, no live calls. `make fvt` is the slower
function-verification suite (below).

## Local development

On Linux, Docker requires Colima:

```bash
colima start    # required before make start / make fvt
```

`make start` and `bash scripts/docker.sh start` both check the daemon and hint `colima start` if down.

Two test tiers:

| Tier | Command | Speed | Requires container |
|------|---------|-------|--------------------|
| Unit | `make unit` | ~1s | No (runs in .venv) |
| Function-verification | `make fvt` | ~30s | Yes (`make start` first) |

`make unit` is the fast inner-loop check and the only pre-PR gate. `make fvt` exercises every MCP tool
end-to-end against a live server.

**`make fvt` *skips* (does not fail) when no server is up** — the session aborts if `GET
{FVT_BASE_URL}/health` doesn't answer within 2s. A green run against nothing is silent, which is why CI never
points pytest at `tests/` wholesale.

### The FVT suite is transport-parameterised

54 tests (1 tool-registration check + 53 parametrized invocations). It runs against **this server over SSE**
or **the open-vMCP gateway over Streamable HTTP**, configured entirely by env:

| Var | Default | Notes |
|-----|---------|-------|
| `FVT_BASE_URL` | `http://localhost:8000` | |
| `FVT_MCP_PATH` | `/sse` | the gateway's passthrough route is `/mcp/rs-mcp` |
| `FVT_TRANSPORT` | `sse` | `sse` or `streamable-http`; anything else raises |
| `FVT_BEARER` | `""` | no `Authorization` header when empty |

`make fvt-vmcp` sets all four to run through the gateway — which is what makes the gateway record
`tool_calls` rows for its dashboard. The suite targets the *unprefixed* passthrough route on purpose: the
aggregate endpoint would namespace tools as `rs-mcp__search_wiki`, and the suite asserts bare names.

### scripts/fvt_traffic.sh + Dockerfile.fvt

`scripts/fvt_traffic.sh` replays the suite through the gateway **on an infinite loop** (`VMCP_URL` /
`AUTH_URL`, default the in-cluster services; `FVT_INTERVAL_SECONDS`, default 900; `FVT_USER`, default
`fvt-runner`; `FVT_CODE`, **required** — the runner's password/pin). It **signs in to platform-auth for a
real RS256 token** (vMCP verifies signatures, so the old forged bearer is rejected), self-provisioning the
account (`POST /auth/identities`, then `/auth/token` if it exists) and refreshing each run. It runs on the
**host, not as a Pod**, pointing both URLs at `https://api-andres.project-platform.me` (nginx routes `/mcp`
and `/auth` to the same services); see platform-cicd for the host unit. It keeps the dashboard's Recent Calls
populated between real traffic.

`Dockerfile.fvt` packages it. It is **deliberately not the production image**: production is a hardened
minimal UBI9 runtime with no pytest, and adding test deps to ship a traffic generator would widen the attack
surface of the thing that serves MCP. (`Dockerfile.fvt.dockerignore` exists because the root `.dockerignore`
strips `tests/` and `scripts/` — exactly what this image needs.)

> **This runs as a HOST container** (see platform-cicd), not a Kubernetes workload — it hits the platform's
> public API from outside the cluster. That also settles the old Deployment-vs-CronJob question (the script
> never exits, so a CronJob Pod would hang forever): a long-lived host container with its own `while true`
> loop, restarted by its unit.

## Dependency locking

`requirements.txt` (committed) is the locked, hash-verified runtime dep list, generated from
`pyproject.toml` via `pip-tools`. The container build consumes it with `pip install -r requirements.txt
--require-hashes` so image layer hashes stay stable.

Regenerate after editing the `[project] dependencies` block in `pyproject.toml`:

```bash
make lock
```

The dev `.venv` uses `pip install -e .[test]` (loose constraints, editable) — `requirements.txt` is for
downstream reproducibility, not daily dev. Verify it installs cleanly in a fresh env:

```bash
python3 -m venv /tmp/lock-verify
/tmp/lock-verify/bin/pip install -r requirements.txt --require-hashes
```

## Gotchas

- **Python version conflict.** `.python-version` and the checked-in `.venv` are **3.14.4**, but
  `pyproject.toml` requires `>=3.12`, ruff targets `py312`, CI pins 3.12, and both images are 3.12. Local dev
  and CI/prod run different minors.
- **`_constants.py` is consumed via `from ._constants import *`**, which is why ruff globally ignores
  `F403`/`F405` — a genuinely undefined name in a tool module **will not be caught by lint**.
- **`geprice.com/api/items` returns 403**, so one FVT case is a known xfail. It and the RS3 GE detail
  endpoint are `GEPRICE_CATALOG_URL` / `RS3_GE_DETAIL_URL` in `config.py`, pointable at a mirror without a
  code change.
- **The container runs `--read-only`** with a 16 MB `/tmp` tmpfs, `--cap-drop=ALL`, `--memory 512m`. Anything
  writing outside `/tmp` or `/logs` passes under `make dev` and fails in the container.
- **No typechecker.** `ruff check` (lint) and `ruff format --check` (formatting) are the static gates — CI
  runs both; there is no type checker.

## Security

See the wiki [Security](https://github.com/AndresI19/rs-mcp-server/wiki/Security) page for the hardened
runtime contract (read-only rootfs, dropped Linux capabilities, Trivy gate in CI) and residual risks. The
`image-scan` job in `.github/workflows/test.yml` enforces the vulnerability gate on every PR.
