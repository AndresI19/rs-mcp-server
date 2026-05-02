.PHONY: install dev start stop logs smoke-test test

install:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt

dev:
	.venv/bin/python server.py

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
