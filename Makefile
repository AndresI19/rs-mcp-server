.PHONY: install dev start stop logs unit fvt lock

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

# Regenerate requirements.txt from pyproject.toml (run after editing the [project] dependencies block).
lock:
	.venv/bin/pip-compile --generate-hashes pyproject.toml -o requirements.txt
