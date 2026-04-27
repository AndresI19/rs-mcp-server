.PHONY: install dev

install:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt

dev:
	.venv/bin/python server.py
