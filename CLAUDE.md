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

TLS is opt-in via a mounted cert directory — the server resolves its listener mode at startup from `/etc/tls_certs` (see `src/rs_mcp_server/tls.py`):

| Cert dir | Listener |
|----------|----------|
| Not mounted | Plain HTTP (default) |
| Mounted, empty / no usable pair | HTTPS with a self-signed fallback cert |
| Mounted with `tls.crt`+`tls.key` (or `fullchain.pem`+`privkey.pem`, or `cert.pem`+`key.pem`) | HTTPS with those certs |

Run with TLS locally: `TLS_CERTS_DIR=/path/to/certs make start` (mounts the dir read-only at `/etc/tls_certs` and polls health over https). The same port `8000` carries HTTP or HTTPS — there is no second port. Full rationale in [docs/security.md](docs/security.md#transport-security-tls).

## Endpoints

| Path | Purpose |
|------|---------|
| `GET /health` | Liveness check — returns `{"status": "ok"}` |
| `GET /sse` | MCP SSE connection (Claude Desktop connects here) |
| `POST /messages` | MCP message transport |

## Logs

While the container runs, tail with `make logs` (delegates to `scripts/docker.sh logs`). Logs are persisted in the `rs-mcp-server-logs` docker volume, so they survive container removal and can still be tailed after `make stop`.

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

See [docs/security.md](docs/security.md) for the hardened runtime contract (read-only rootfs, dropped Linux capabilities, Trivy gate in CI) and the residual risks the container does not cover. The `image-scan` job in `.github/workflows/test.yml` enforces the vulnerability gate on every PR.
