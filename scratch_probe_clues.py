"""Investigation probe: drive solve_clue across every documented clue step type."""
import asyncio
import re

import httpx

from rs_mcp_server.tools.clues import _load_format, solve_clue

UA = {"User-Agent": "probe"}


def wikitext(game, page):
    api = "https://oldschool.runescape.wiki/api.php" if game == "osrs" else "https://runescape.wiki/api.php"
    r = httpx.get(api, params={"action": "parse", "page": page, "prop": "wikitext",
                               "format": "json", "formatversion": 2}, headers=UA, timeout=25)
    return r.json().get("parse", {}).get("wikitext", "")


def status_of(res: str) -> str:
    if res.startswith("**"):
        return "SOLVED"
    if "did you mean" in res.lower() or "Did you mean" in res:
        return "DID-YOU-MEAN"
    if "doesn't have a documented" in res:
        return "FORMAT N/A"
    return "NO MATCH"


async def probe(label, game, clue, note=""):
    res = await solve_clue(clue, game)
    print(f"  [{status_of(res):12}] {label:18} ({game})  q={clue[:50]!r}")
    if note:
        print(f"                 └─ {note}")


async def main():
    print("######## HANDLED step types (tool indexes these 4 pages) ########")
    for game, fmt in [("osrs", "anagram"), ("osrs", "cryptic"), ("osrs", "emote"),
                      ("osrs", "cipher"), ("rs3", "anagram"), ("rs3", "cryptic"), ("rs3", "emote")]:
        ents = await _load_format(game, fmt)
        if not ents:
            print(f"  [NO INDEX    ] {fmt:18} ({game})")
            continue
        await probe(fmt, game, ents[0]["clue_text"])

    print("\n######## UNHANDLED step types (not in any index) ########")
    # Text-based → addressable gaps the tool COULD index
    await probe("coordinate", "osrs", "04 degrees 13 minutes south 16 degrees 25 minutes east",
                "degrees/minutes → location: pure text, ADDRESSABLE")
    wt = wikitext("osrs", "Treasure Trails/Guide/Challenge scrolls")
    q = next((m.strip() for m in re.findall(r'\n\| *([A-Z][^|\n{}]{12,80}\?)', wt)), "How many bananas can a backpack hold?")
    await probe("challenge scroll", "osrs", q, "NPC Q&A: pure text, ADDRESSABLE")
    await probe("simple clue", "rs3", "Speak to the bartender of the Rusty Anchor in Port Sarim",
                "RS3 simple step: text, ADDRESSABLE")
    # Non-text → tool's text input can't even represent these
    await probe("hot/cold", "osrs", "strange device gets hot near the dig spot",
                "proximity device → no fixed text answer")
    await probe("compass", "rs3", "compass clue", "arrow points to a spot → no text query")
    await probe("scan", "rs3", "scan clue Ardougne", "in-game scanner proximity → no text query")
    await probe("map", "osrs", "hand-drawn map to a dig location", "image clue → no text exists")
    await probe("puzzle box", "osrs", "sliding puzzle box", "interactive puzzle → solved in client")
    await probe("light box", "osrs", "light box puzzle", "interactive logic puzzle")
    await probe("celtic knot", "rs3", "celtic knot puzzle", "interactive puzzle")
    await probe("lockbox", "rs3", "lockbox puzzle", "interactive puzzle")


asyncio.run(main())
