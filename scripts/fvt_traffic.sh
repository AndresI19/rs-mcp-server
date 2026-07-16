#!/usr/bin/env bash
# Scheduled FVT traffic runner.
#
# Replays the function-verification suite through the open-vMCP gateway on an interval, instead of
# straight at this server. The gateway is what records a `tool_calls` row for every call that
# crosses it, so this is the only path that puts real traffic on its dashboard — an FVT run against
# port 8000 would exercise the same tools and leave the dashboard empty.
#
# It is a *test* suite doing double duty as a traffic source, which means the dashboard is showing
# genuine tool invocations against live wiki/GE/hiscores data, not seeded rows. A failing run is
# therefore real signal (the gateway, the server, or an upstream API is broken) — it is logged and
# the loop carries on, because a demo stack should not lose its traffic to one flaky wiki fetch.
#
# Config (all optional except FVT_CODE):
#   VMCP_URL              gateway base URL              (default http://vmcp:8001)
#   AUTH_URL              platform-auth base URL        (default http://platform-auth:8002)
#   FVT_INTERVAL_SECONDS  seconds between runs          (default 900)
#   FVT_USER              the runner's username         (default fvt-runner)
#   FVT_CODE              the runner's password/pin     (REQUIRED, at least 4 chars)
#
# In-cluster the defaults reach the services over cluster DNS. From OUTSIDE the cluster (this runner now
# lives on the host, not as a Pod), point BOTH URLs at the public API host — nginx routes /mcp and
# /auth there to the same services:
#   VMCP_URL=https://api-andres.project-platform.me  AUTH_URL=https://api-andres.project-platform.me
set -uo pipefail

VMCP_URL="${VMCP_URL:-http://vmcp:8001}"
AUTH_URL="${AUTH_URL:-http://platform-auth:8002}"
INTERVAL="${FVT_INTERVAL_SECONDS:-900}"
FVT_USER="${FVT_USER:-fvt-runner}"
FVT_CODE="${FVT_CODE:?set FVT_CODE to the fvt-runner password or pin, at least 4 chars}"

# A REAL signed token, not a forgery. vMCP verifies RS256 against platform-auth's JWKS now (issuer and
# audience checked too), so a bare base64url payload is rejected outright — which is why the old forged
# token silently 401'd every run and the dashboard stayed empty. The runner is a first-class account
# instead: username FVT_USER, password FVT_CODE. It self-provisions and signs in — POST /auth/identities
# returns a token on 201 (created) or 409 if the name is already taken, in which case POST /auth/token
# exchanges the credentials for one. The token's `sub`/`username` claims are what put FVT_USER in the
# dashboard's User column.
extract_token() { python3 -c 'import sys,json;print((json.load(sys.stdin) or {}).get("token",""))' 2>/dev/null; }

get_token() {
  local out tok
  out="$(curl -sS -X POST "${AUTH_URL}/auth/identities" -H 'Content-Type: application/json' \
         -d "{\"username\":\"${FVT_USER}\",\"password\":\"${FVT_CODE}\"}" 2>/dev/null)"
  tok="$(printf '%s' "$out" | extract_token)"
  if [ -z "$tok" ]; then
    out="$(curl -sS -X POST "${AUTH_URL}/auth/token" -H 'Content-Type: application/json' \
           -d "{\"username\":\"${FVT_USER}\",\"password\":\"${FVT_CODE}\"}" 2>/dev/null)"
    tok="$(printf '%s' "$out" | extract_token)"
  fi
  printf '%s' "$tok"
}

# The gateway's per-server route is a 1:1 passthrough, so tool names stay unprefixed and the suite
# runs unmodified. (The aggregate /mcp endpoint would namespace them as rs-mcp__search_wiki.)
export FVT_BASE_URL="$VMCP_URL"
export FVT_MCP_PATH="/mcp/rs-mcp"
export FVT_TRANSPORT="streamable-http"

echo "[fvt-traffic] target=${FVT_BASE_URL}${FVT_MCP_PATH} transport=${FVT_TRANSPORT} auth=${AUTH_URL} user=${FVT_USER} interval=${INTERVAL}s"

echo "[fvt-traffic] waiting for the gateway to answer /health…"
until curl -sf "${VMCP_URL}/health" >/dev/null 2>&1; do sleep 5; done
echo "[fvt-traffic] gateway is up"

while true; do
  echo "[fvt-traffic] --- run starting at $(date -u +%FT%TZ) ---"
  # A fresh token each run — cheaper than tracking the token's 24h expiry, and it re-provisions the
  # account automatically if it is ever cleared.
  FVT_BEARER="$(get_token)"
  if [ -z "$FVT_BEARER" ]; then
    echo "[fvt-traffic] could NOT get a token from ${AUTH_URL} (check FVT_CODE and reachability) — skipping this run"
    sleep "$INTERVAL"; continue
  fi
  export FVT_BEARER
  # -p no:cacheprovider: the container has nothing to gain from a .pytest_cache and may be read-only.
  if pytest tests/fvt -m fvt -q -p no:cacheprovider; then
    echo "[fvt-traffic] run passed"
  else
    echo "[fvt-traffic] run FAILED (exit $?) — the calls that executed are still recorded; continuing"
  fi
  echo "[fvt-traffic] sleeping ${INTERVAL}s"
  sleep "$INTERVAL"
done
