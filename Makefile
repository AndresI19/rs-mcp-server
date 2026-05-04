.PHONY: install dev start stop logs smoke-test test lock

install:
	python3 -m venv .venv
	.venv/bin/pip install -q -e ".[test]"

dev:
	.venv/bin/python -m rs_mcp_server.server

start:
	@bash scripts/start.sh

stop:
	@bash scripts/stop.sh

logs:
	@tail -f /tmp/mcp-server.log

smoke-test:
	.venv/bin/python scripts/smoke_test_tools.py

test:
	.venv/bin/python -m pytest tests/ -v

# Regenerate requirements.txt from pyproject.toml (run after editing the [project] dependencies block).
lock:
	.venv/bin/pip-compile --generate-hashes pyproject.toml -o requirements.txt
