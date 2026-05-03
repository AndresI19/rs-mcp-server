#!/usr/bin/env bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="/tmp/mcp-server.log"
HEALTH_URL="http://localhost:8000/health"

if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
    echo "Server already running — http://localhost:8000/sse"
    exit 0
fi

: > "$LOG_FILE"

ptyxis -T "RS MCP Server" -- bash -c "
cd '$REPO_ROOT'
printf '\033[1;32m=== RS MCP Server ===\033[0m\n'
.venv/bin/python -m uvicorn rs_mcp_server.server:web --host \"\${MCP_HOST:-127.0.0.1}\" --port 8000 2>&1 | tee '$LOG_FILE'
printf '\nServer stopped — press Enter to close\n'
read
" &

printf 'Waiting for server'
i=0
while [ $i -lt 15 ]; do
    i=$((i+1))
    sleep 1
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        printf ' ready.\n'
        printf '  MCP endpoint: http://localhost:8000/sse\n'
        printf '  Logs:         tail -f %s\n' "$LOG_FILE"
        printf '  To stop:      make -C %s stop\n' "$REPO_ROOT"
        exit 0
    fi
    printf '.'
done

printf ' timed out.\n'
printf 'Check logs: tail -f %s\n' "$LOG_FILE"
exit 1
