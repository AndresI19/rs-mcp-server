.PHONY: install dev start stop logs unit fvt fvt-vmcp lock

.DEFAULT_GOAL := unit

install:
	python3 -m venv .venv
	.venv/bin/pip install -q -e ".[test]"

dev:
	.venv/bin/python -m rs_mcp_server.server

start:
	@bash scripts/docker.sh start

stop:
	@bash scripts/docker.sh stop

logs:
	@bash scripts/docker.sh logs

unit:
	.venv/bin/python -m pytest tests/unit -v

fvt:
	.venv/bin/python -m pytest tests/fvt -v -m fvt

# The same suite, driven through the open-vMCP gateway instead of straight at the container — so the
# calls are recorded and land on the gateway's dashboard. Expects the gateway reachable at
# VMCP_URL (default: a local `npm run dev` on 8001). Point it elsewhere with VMCP_URL=…
# In the compose stack this runs continuously as the `fvt-traffic` service; this is the manual shot.
fvt-vmcp:
	FVT_BASE_URL=$${VMCP_URL:-http://localhost:8001} \
	FVT_MCP_PATH=/mcp/rs-mcp \
	FVT_TRANSPORT=streamable-http \
	FVT_BEARER=$$(printf '%s' '{"user":"local-dev"}' | base64 -w0 | tr '+/' '-_' | tr -d '=') \
	.venv/bin/python -m pytest tests/fvt -v -m fvt

# Regenerate requirements.txt from pyproject.toml (run after editing the [project] dependencies block).
lock:
	.venv/bin/pip-compile --generate-hashes pyproject.toml -o requirements.txt
