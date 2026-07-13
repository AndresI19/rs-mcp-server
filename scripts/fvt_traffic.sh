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
# Config (all optional):
#   VMCP_URL              gateway base URL              (default http://vmcp:8001)
#   FVT_INTERVAL_SECONDS  seconds between runs          (default 900)
#   FVT_USER              user id the calls attribute to (default fvt-runner)
set -uo pipefail

VMCP_URL="${VMCP_URL:-http://vmcp:8001}"
INTERVAL="${FVT_INTERVAL_SECONDS:-900}"
FVT_USER="${FVT_USER:-fvt-runner}"

# vMCP's v1 auth decodes the bearer without verifying it, and config/auth.json maps the `user` claim
# to the user id — so a bare base64url JSON payload is a valid token. That id is what the dashboard
# shows in the User column, which is why the calls read as `fvt-runner` rather than as anonymous.
mint_token() {
  printf '%s' "{\"user\":\"${FVT_USER}\"}" | base64 -w0 | tr '+/' '-_' | tr -d '='
}

# The gateway's per-server route is a 1:1 passthrough, so tool names stay unprefixed and the suite
# runs unmodified. (The aggregate /mcp endpoint would namespace them as rs-mcp__search_wiki.)
export FVT_BASE_URL="$VMCP_URL"
export FVT_MCP_PATH="/mcp/rs-mcp"
export FVT_TRANSPORT="streamable-http"
export FVT_BEARER="$(mint_token)"

echo "[fvt-traffic] target=${FVT_BASE_URL}${FVT_MCP_PATH} transport=${FVT_TRANSPORT} user=${FVT_USER} interval=${INTERVAL}s"

echo "[fvt-traffic] waiting for the gateway to answer /health…"
until curl -sf "${VMCP_URL}/health" >/dev/null 2>&1; do sleep 5; done
echo "[fvt-traffic] gateway is up"

while true; do
  echo "[fvt-traffic] --- run starting at $(date -u +%FT%TZ) ---"
  # -p no:cacheprovider: the container has nothing to gain from a .pytest_cache and may be read-only.
  if pytest tests/fvt -m fvt -q -p no:cacheprovider; then
    echo "[fvt-traffic] run passed"
  else
    echo "[fvt-traffic] run FAILED (exit $?) — traffic still recorded; continuing"
  fi
  echo "[fvt-traffic] sleeping ${INTERVAL}s"
  sleep "$INTERVAL"
done
