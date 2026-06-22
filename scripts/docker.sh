#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="rs-mcp-server:dev"
CONTAINER_NAME="rs-mcp-server"
VOLUME_NAME="rs-mcp-server-logs"
CONTAINER_LOG="/logs/uvicorn.log"

# Host port to publish the server on. The container always listens internally on 8000;
# this only remaps the host side (-p ${PORT}:8000), so any free host port works:
#   PORT=9000 make start  →  http://localhost:9000/sse
PORT="${PORT:-8000}"

# TLS is opt-in via a host cert directory mounted onto /etc/tls_certs. When TLS_CERTS_DIR
# is set the server terminates HTTPS on the same port (real certs if present, else a
# self-signed fallback), so the health poll must speak https and tolerate self-signed
# certs (-k). When unset, no mount → the server serves plain HTTP.
if [[ -n "${TLS_CERTS_DIR:-}" ]]; then
    SCHEME="https"
    HEALTH_CURL_OPTS=(-sfk)
else
    SCHEME="http"
    HEALTH_CURL_OPTS=(-sf)
fi
HEALTH_URL="${SCHEME}://localhost:${PORT}/health"

check_docker() {
    if ! docker info >/dev/null 2>&1; then
        cat <<EOF >&2
Docker daemon not reachable. On Linux, start Colima first:
  colima start
Then re-run this script.
EOF
        exit 1
    fi
}

cmd_start() {
    check_docker
    if curl "${HEALTH_CURL_OPTS[@]}" "$HEALTH_URL" >/dev/null 2>&1; then
        echo "Server already running — ${SCHEME}://localhost:${PORT}/sse"
        exit 0
    fi

    docker volume create "$VOLUME_NAME" >/dev/null

    echo "Building image $IMAGE_NAME..."
    docker build --pull -t "$IMAGE_NAME" "$REPO_ROOT"
    docker image prune -f >/dev/null

    # Optional read-only cert mount. Its presence is what flips the server to HTTPS.
    local tls_mount=()
    if [[ -n "${TLS_CERTS_DIR:-}" ]]; then
        tls_mount=(-v "${TLS_CERTS_DIR}:/etc/tls_certs:ro")
        echo "TLS enabled — mounting ${TLS_CERTS_DIR} → /etc/tls_certs (ro)"
    fi

    echo "Starting container $CONTAINER_NAME..."
    docker run --rm -d \
        --name "$CONTAINER_NAME" \
        -p "${PORT}:8000" \
        -v "${VOLUME_NAME}:/logs" \
        "${tls_mount[@]}" \
        -e "LOGFILE=${CONTAINER_LOG}" \
        --read-only \
        --tmpfs /tmp:rw,size=16m,mode=1777 \
        --cap-drop=ALL \
        --security-opt no-new-privileges:true \
        --memory 512m \
        --pids-limit 100 \
        "$IMAGE_NAME" >/dev/null

    printf 'Waiting for server'
    for _ in $(seq 1 30); do
        sleep 1
        if curl "${HEALTH_CURL_OPTS[@]}" "$HEALTH_URL" >/dev/null 2>&1; then
            printf ' ready.\n'
            printf '  MCP endpoint: %s://localhost:%s/sse\n' "$SCHEME" "$PORT"
            printf '  Logs:         bash %s logs\n' "$0"
            printf '  To stop:      bash %s stop\n' "$0"
            exit 0
        fi
        printf '.'
    done
    printf ' timed out.\n'
    printf 'Check logs: bash %s logs\n' "$0"
    exit 1
}

cmd_stop() {
    if ! docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        echo "Container ${CONTAINER_NAME} not running."
        exit 0
    fi
    docker rm -f "$CONTAINER_NAME" >/dev/null
    echo "Container ${CONTAINER_NAME} stopped."
}

cmd_logs() {
    # If the container is running, exec into it — cheapest path.
    if docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        exec docker exec "$CONTAINER_NAME" tail -f "$CONTAINER_LOG"
    fi

    # Container not running. Logs may still be in the volume from the last run.
    if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
        echo "No log volume yet — start the container first: bash $0 start" >&2
        exit 1
    fi
    if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
        echo "Image ${IMAGE_NAME} not present and container not running." >&2
        echo "Run 'bash $0 start' to rebuild and start the container." >&2
        exit 1
    fi
    exec docker run --rm \
        -v "${VOLUME_NAME}:/logs" \
        --entrypoint tail \
        "$IMAGE_NAME" -f "$CONTAINER_LOG"
}

cmd_clean() {
    if docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        docker rm -f "$CONTAINER_NAME" >/dev/null
    fi
    # Also kill any orphan sidecars still holding the log volume (e.g. a backgrounded
    # `logs` invocation whose tail-f was killed before the sidecar exited).
    local sidecars
    sidecars=$(docker ps -aq --filter "volume=${VOLUME_NAME}" 2>/dev/null || true)
    if [[ -n "$sidecars" ]]; then
        # shellcheck disable=SC2086  # intentional word-splitting of the ID list
        docker rm -f $sidecars >/dev/null
    fi
    docker volume rm "$VOLUME_NAME" >/dev/null 2>&1 || true
    docker image rm "$IMAGE_NAME" >/dev/null 2>&1 || true
    docker image prune -f >/dev/null
    echo "Cleaned: removed container, removed volume, removed ${IMAGE_NAME}, pruned dangling layers."
}

usage() {
    cat <<EOF
Usage: $(basename "$0") {start|stop|logs|clean}

  start  Check docker, build image, run container detached on port 8000.
  stop   Stop and remove the container (docker rm -f).
  logs   Tail -f the log file from inside the container (or from the
         persistent volume if the container is not currently running).
  clean  Stop container, remove image, remove log volume, prune layers.

Env:
  TLS_CERTS_DIR  Host directory mounted read-only onto /etc/tls_certs. When set,
                 the server serves HTTPS on port 8000 (real certs if the dir holds
                 a tls.crt/tls.key, fullchain.pem/privkey.pem, or cert.pem/key.pem
                 pair; otherwise a self-signed fallback). When unset, plain HTTP.

Container: ${CONTAINER_NAME}
Image:     ${IMAGE_NAME}
Log volume: ${VOLUME_NAME}  (container path: ${CONTAINER_LOG})
EOF
}

case "${1:-}" in
    start) cmd_start ;;
    stop)  cmd_stop ;;
    logs)  cmd_logs ;;
    clean) cmd_clean ;;
    -h|--help|"") usage ;;
    *)
        usage >&2
        echo >&2
        echo "error: unknown subcommand: $1" >&2
        exit 2
        ;;
esac
