"""Generate baked coordinate-clue datasets from the RuneScape wikis.

Coordinate clues are a finite, static dataset, and parsing the guide page's 167
per-coordinate sections is expensive and fragile — so we do it ONCE here, offline,
and commit the result. The runtime `solve_clue` tool loads the JSON and resolves
coordinate clues with no network call. Re-run manually when coordinate clues change:

    .venv/bin/python scripts/generate_clue_data.py

Writes src/rs_mcp_server/resources/clues/coordinates_{osrs,rs3}.json. The exact dig
spot lives in a map image, so each entry resolves to the degrees/shorthand, the
requirements, whether the spot is guarded, and a deep link to the wiki section (whose
map shows precisely where to dig).
"""
import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import httpx

from rs_mcp_server.tools.clues import normalize_coordinate

GAMES = {
    "osrs": "https://oldschool.runescape.wiki",
    "rs3": "https://runescape.wiki",
}
# Each game anchors coordinate sections differently and lays out its table differently:
#   OSRS: <span id="2xx"> … 5xx, tier in the leading digit; cols degrees|short|reqs|fight
#   RS3:  <span id="medium-coord-NN">, tier in the prefix; cols degrees|location|travel|…
_TIER_BY_PREFIX = {"2": "medium", "3": "hard", "4": "elite", "5": "master"}
_ANCHOR_RE = {
    "osrs": r'<span id="([2-5]\d\d)">',
    "rs3": r'<span id="((?:medium|hard|elite|master)-coord-\d+)">',
}
_PAGE = "Treasure Trails/Guide/Coordinates"


def _tier_of(game: str, anchor: str) -> str:
    return _TIER_BY_PREFIX.get(anchor[0], "") if game == "osrs" else anchor.split("-", 1)[0]
_OUT = Path(__file__).resolve().parent.parent / "src/rs_mcp_server/resources/clues"


class _FirstDataRow(HTMLParser):
    """Capture the first non-header data row of one table as [{text, alts}, ...]."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.row: list[dict] | None = None
        self._cells: list[dict] | None = None
        self._cell: dict | None = None
        self._has_th = False

    def handle_starttag(self, tag, attrs):
        if self.row is not None:
            return
        if tag == "tr":
            self._cells, self._has_th = [], False
        elif tag == "th":
            self._has_th = True
        elif tag == "td" and self._cells is not None:
            self._cell = {"text": [], "alts": []}
        elif tag == "img" and self._cell is not None:
            alt = dict(attrs).get("alt")
            if alt:
                self._cell["alts"].append(alt)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"].append(data)

    def handle_endtag(self, tag):
        if self.row is not None:
            return
        if tag == "td" and self._cell is not None:
            text = " ".join("".join(self._cell["text"]).split())
            self._cells.append({"text": text, "alts": self._cell["alts"]})
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            if not self._has_th and len(self._cells) >= 3:
                self.row = self._cells
            self._cells = None


def _fetch(base: str) -> str:
    r = httpx.get(
        f"{base}/api.php",
        params={"action": "parse", "page": _PAGE, "prop": "text",
                "format": "json", "formatversion": 2},
        headers={"User-Agent": "rs-mcp-clue-gen/1.0"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["parse"]["text"]


def _first_table(chunk: str) -> str | None:
    m = re.search(r'<table[^>]*\bwikitable\b.*?</table>', chunk, re.S)
    return m.group(0) if m else None


def generate(game: str) -> dict:
    base = GAMES[game]
    html = _fetch(base)
    coords: dict[str, dict] = {}
    # Split on each coordinate anchor; odd parts are the id, even parts the section.
    parts = re.split(_ANCHOR_RE[game], html)
    for i in range(1, len(parts), 2):
        anchor, chunk = parts[i], parts[i + 1]
        table = _first_table(chunk)
        if not table:
            continue
        parser = _FirstDataRow()
        parser.feed(table)
        row = parser.row
        if not row or len(row) < 2:
            continue
        # Both games put the degrees in column 0; the key is derived from them so it
        # matches what the runtime resolver computes from a player's query.
        key = normalize_coordinate(row[0]["text"])
        if not key:
            continue
        entry = {
            "shorthand": key,
            "degrees": row[0]["text"],
            "tier": _tier_of(game, anchor),
            "wiki_url": f"{base}/w/Treasure_Trails/Guide/Coordinates#{anchor}",
        }
        if game == "osrs":
            entry["requirements"] = (row[2]["text"] if len(row) > 2 else "") or "None"
            fight_alts = row[3]["alts"] if len(row) > 3 else []
            entry["fight"] = "yes" if any("yes" in a.lower() for a in fight_alts) else "no"
        else:  # rs3: Coordinates | Location | Suggested travel | Image | Map
            if len(row) > 1 and row[1]["text"]:
                entry["location"] = row[1]["text"]
            if len(row) > 2 and row[2]["text"]:
                entry["travel"] = row[2]["text"]
        coords[key] = entry
    return coords


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    for game in GAMES:
        coords = generate(game)
        payload = {
            "_generated": date.today().isoformat(),
            "_source": f"{GAMES[game]}/w/{_PAGE.replace(' ', '_')}",
            "coordinates": coords,
        }
        path = _OUT / f"coordinates_{game}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print(f"{game}: {len(coords)} coordinates -> {path.relative_to(_OUT.parents[3])}")


if __name__ == "__main__":
    main()
