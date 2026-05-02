#!/usr/bin/env python3
"""End-to-end smoke test for all MCP tools over SSE.

Run after `make start`. Exits 0 on full pass, 1 on any failure.
"""
import argparse
import asyncio
import sys

import httpx
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

EXPECTED_TOOLS = {"search_wiki", "get_item_price", "get_player_stats", "get_quest_info"}

CASES = [
    ("search_wiki",      {"query": "fishing", "game": "rs3"},                ["**Fishing**", "Wiki)"]),
    ("search_wiki",      {"query": "ardougne", "game": "osrs"},              ["OSRS Wiki)"]),
    ("get_item_price",   {"item_name": "shark", "game": "osrs"},             ["**Shark**", "OSRS Grand Exchange", "Instant buy:"]),
    ("get_item_price",   {"item_name": "Abyssal whip", "game": "rs3"},       ["**Abyssal whip**", "RS3 Grand Exchange", "Price:"]),
    ("get_player_stats", {"username": "Lynx Titan", "game": "osrs"},         ["OSRS Hiscores", "Total level"]),
    ("get_player_stats", {"username": "Zezima", "game": "rs3"},              ["RS3 Hiscores", "Total level"]),
    ("get_quest_info",   {"quest_name": "Cook's Assistant", "game": "osrs"}, ["**Cook's Assistant**", "Difficulty"]),
    ("get_quest_info",   {"quest_name": "Dragon Slayer", "game": "rs3"},     ["**Dragon Slayer**", "Difficulty"]),
    ("get_quest_info",   {"quest_name": "Dragon Slayer I", "game": "rs3"},   ["Did you mean"]),
    ("get_quest_info",   {"quest_name": "zzznotaquestzzz", "game": "rs3"},   ["No quest found"]),
]


def preflight(base_url: str) -> None:
    try:
        r = httpx.get(f"{base_url}/health", timeout=2.0)
        r.raise_for_status()
    except Exception as e:
        print(f"FAIL: server unreachable at {base_url} ({e}). Start it first: make start", file=sys.stderr)
        sys.exit(1)


def extract_text(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")


async def run_cases(base_url: str, verbose: bool) -> int:
    failures = 0
    async with sse_client(f"{base_url}/sse") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            label = "list_tools"
            if names == EXPECTED_TOOLS:
                print(f"[PASS] {label} → {sorted(names)}")
            else:
                failures += 1
                print(f"[FAIL] {label}: expected {sorted(EXPECTED_TOOLS)}, got {sorted(names)}")

            for tool_name, args, expected in CASES:
                arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
                label = f"{tool_name}({arg_str})"
                try:
                    result = await session.call_tool(tool_name, args)
                    if result.isError:
                        failures += 1
                        print(f"[FAIL] {label}: isError=True — {extract_text(result)[:200]}")
                        continue
                    text = extract_text(result)
                    missing = [s for s in expected if s not in text]
                    if missing:
                        failures += 1
                        print(f"[FAIL] {label}: missing {missing} in:\n  {text[:300]}")
                    else:
                        print(f"[PASS] {label}")
                        if verbose:
                            print("  " + "\n  ".join(text.splitlines()[:6]))
                except Exception as e:
                    failures += 1
                    print(f"[FAIL] {label}: raised {type(e).__name__}: {e}")

    return failures


def main() -> int:
    p = argparse.ArgumentParser(description="Smoke test all MCP tools over SSE.")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--verbose", "-v", action="store_true", help="print first lines of each successful response")
    args = p.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    preflight(base_url)

    failures = asyncio.run(run_cases(base_url, args.verbose))
    total = len(CASES) + 1
    passed = total - failures
    print(f"\nSummary: {passed}/{total} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
