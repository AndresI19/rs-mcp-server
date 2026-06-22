"""solve_clue tool — RuneScape Wiki Treasure Trails clue databases.

Supports four text-based clue formats (anagram, cryptic, emote, cipher) across
both games. The wiki organizes each format on a single page (per game) with
per-tier h3 sections; this tool walks h3+table tags in document order, builds a
flat index of {tier, format, clue_text, solution, ...} entries, and supports
exact / fuzzy / no-match lookup.
"""
import html
import re
from html.parser import HTMLParser

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get
from ._wiki_parsing import collapse_whitespace as _collapse

_TTL = 3600

_FORMATS = ("anagram", "cryptic", "emote", "cipher")
_TIERS = ("beginner", "easy", "medium", "hard", "elite", "master")

# Per-game page titles. None = not supported on this game (returns a polite message).
_PAGES = {
    "osrs": {
        "anagram": "Treasure Trails/Guide/Anagrams",
        "cryptic": "Treasure Trails/Guide/Cryptic clues",
        "emote":   "Treasure Trails/Guide/Emote clues",
        "cipher":  "Treasure Trails/Guide/Ciphers",
    },
    "rs3": {
        "anagram": "Treasure Trails/Guide/Anagrams",
        "cryptic": "Treasure Trails/Guide/Cryptics",
        "emote":   "Treasure Trails/Guide/Emotes",
        "cipher":  None,  # RS3 doesn't have ciphers as a clue format
    },
}


@instrument("solve_clue")
async def solve_clue(
    clue_text: str,
    game: str = "rs3",
    clue_format: str | None = None,
    tier: str | None = None,
) -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not clue_text.strip():
        return "No clue text provided."
    if clue_format is not None:
        clue_format = clue_format.lower()
        if clue_format not in _FORMATS:
            return f"Unknown clue_format '{clue_format}'. Use one of: {', '.join(_FORMATS)}."
    if tier is not None:
        tier = tier.lower()
        if tier not in _TIERS:
            return f"Unknown tier '{tier}'. Use one of: {', '.join(_TIERS)}."

    wiki_label = "RS3" if game == "rs3" else "OSRS"

    if clue_format is not None:
        if _PAGES[game].get(clue_format) is None:
            return f"{wiki_label} doesn't have a documented {clue_format} clue dataset on the wiki."
        entries = await _load_format(game, clue_format)
    else:
        entries = []
        for fmt in _FORMATS:
            if _PAGES[game].get(fmt) is None:
                continue
            entries.extend(await _load_format(game, fmt))

    if tier is not None:
        entries = [e for e in entries if e["tier"] == tier]

    if not entries:
        return f"No clue data available for the requested {wiki_label} filters."

    kind, payload = _match_clues(clue_text, entries)
    if kind == "exact":
        return _render_solution(payload, wiki_label, game)
    if kind == "did_you_mean":
        return _render_did_you_mean(payload, wiki_label)
    return (
        f"No matching clue found for '{clue_text}' on the {wiki_label} wiki. "
        f"Browse the full clue lists at {WIKI_BASE_URLS[game]}Treasure_Trails."
    )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

async def _load_format(game: str, fmt: str) -> list[dict]:
    cache_key = f"clues:{game}:{fmt}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    page = _PAGES[game][fmt]
    if page is None:
        return []

    params = {"action": "parse", "page": page, "prop": "text", **MW_BASE_PARAMS}
    data = await http_get(WIKI_APIS[game], params=params)
    text = data.get("parse", {}).get("text")
    if not text:
        cache.set(cache_key, [], _TTL)
        return []

    entries = _parse_clue_html(text, fmt)
    cache.set(cache_key, entries, _TTL)
    return entries


# ---------------------------------------------------------------------------
# HTML parser (one walker, format-aware row extraction)
# ---------------------------------------------------------------------------

def _parse_clue_html(html_text: str, fmt: str) -> list[dict]:
    """Walk h2/h3 headings + wikitable rows in document order into clue entries."""
    parser = _CluesParser(fmt)
    parser.feed(html_text)
    return parser.entries


def _tier_from_heading(text: str) -> str:
    t = text.lower()
    for tier in _TIERS:
        if tier in t:
            return tier
    return ""


class _CluesParser(HTMLParser):
    """Walk h2/h3 headings + wikitable rows in document order, emitting clue entries.

    Replaces the _HEADING_OR_TABLE regex (which split <h2|h3|table> blocks then fed
    each table body to a separate row parser) with a single pass: heading text sets
    the current tier, and each 2+-column data row in a wikitable becomes an entry via
    the format-specific _row_to_entry. Table depth is tracked so a table nested in a
    cell is ignored; image alt text is captured per cell so emote item icons survive.
    """

    _EXCLUDE_IDS = {"references", "see_also", "trivia", "gallery"}

    def __init__(self, fmt: str) -> None:
        super().__init__(convert_charrefs=True)
        self.fmt = fmt
        self.entries: list[dict] = []
        self.current_tier = ""
        self._heading: str | None = None
        self._heading_id = ""
        self._heading_buf: list[str] = []
        self._depth = 0
        self._in_table = False
        self._target_depth = 0
        self._row: list[dict] | None = None
        self._row_has_th = False
        self._cell: dict | None = None

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag in ("h2", "h3"):
            self._heading = tag
            self._heading_id = ad.get("id", "")
            self._heading_buf = []
        elif tag == "table":
            self._depth += 1
            if not self._in_table and "wikitable" in (ad.get("class") or "").split():
                self._in_table = True
                self._target_depth = self._depth
        elif self._in_table and self._depth == self._target_depth:
            if tag == "tr":
                self._row = []
                self._row_has_th = False
            elif tag == "th":
                self._row_has_th = True
            elif tag == "td" and self._row is not None:
                self._cell = {"text": "", "alts": []}
            elif tag == "img" and self._cell is not None:
                alt = ad.get("alt")
                if alt:
                    self._cell["alts"].append(alt)

    def handle_data(self, data):
        if self._heading is not None:
            self._heading_buf.append(data)
        elif self._in_table and self._depth == self._target_depth and self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag == self._heading:
            self._apply_heading()
            self._heading = None
        elif tag == "table":
            if self._in_table and self._depth == self._target_depth:
                self._in_table = False
            self._depth -= 1
        elif self._in_table and self._depth == self._target_depth:
            if tag == "td" and self._cell is not None and self._row is not None:
                self._row.append(_finalize_cell(self._cell))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                self._emit_row()
                self._row = None

    def _apply_heading(self) -> None:
        text = " ".join("".join(self._heading_buf).split())
        tier = _tier_from_heading(text)
        if tier:
            self.current_tier = tier
        elif self._heading == "h2" and self._heading_id.lower() in self._EXCLUDE_IDS:
            self.current_tier = ""  # leaving the data section

    def _emit_row(self) -> None:
        if self._row_has_th or not self.current_tier or len(self._row) < 2:
            return
        entry = _row_to_entry(self._row, self.fmt, self.current_tier)
        if entry is not None:
            self.entries.append(entry)


def _finalize_cell(cell: dict) -> dict:
    text = _collapse(cell["text"])
    items = ", ".join(_clean_alt(a) for a in cell["alts"]) if cell["alts"] else text
    return {"text": text, "items": items}


# ---------------------------------------------------------------------------
# Format-specific row extraction
# ---------------------------------------------------------------------------

# RS3 anagram pages prefix every clue with this verbose intro; strip it.
_ANAGRAM_PREFIX = re.compile(r"^this anagram reveals who to speak to next:?\s*", re.IGNORECASE)


def _row_to_entry(cells: list[str], fmt: str, tier: str) -> dict | None:
    if fmt == "anagram":
        return _row_anagram(cells, tier)
    if fmt == "cryptic":
        return _row_cryptic(cells, tier)
    if fmt == "emote":
        return _row_emote(cells, tier)
    if fmt == "cipher":
        return _row_cipher(cells, tier)
    return None


def _row_anagram(cells: list[dict], tier: str) -> dict | None:
    clue = _ANAGRAM_PREFIX.sub("", cells[0]["text"]).strip()
    solution = cells[1]["text"] if len(cells) > 1 else ""
    location = cells[2]["text"] if len(cells) > 2 else ""
    if not clue:
        return None
    return {
        "format": "anagram",
        "tier": tier,
        "clue_text": clue,
        "clue_text_lower": clue.lower(),
        "solution": solution,
        "location": location,
    }


def _row_cryptic(cells: list[dict], tier: str) -> dict | None:
    clue = cells[0]["text"]
    solution = cells[1]["text"] if len(cells) > 1 else ""
    location = cells[2]["text"] if len(cells) > 2 else ""
    if not clue:
        return None
    return {
        "format": "cryptic",
        "tier": tier,
        "clue_text": clue,
        "clue_text_lower": clue.lower(),
        "solution": solution,
        "location": location,
    }


def _row_emote(cells: list[dict], tier: str) -> dict | None:
    clue = cells[0]["text"]
    items = cells[1]["items"] if len(cells) > 1 else ""
    location = cells[2]["text"] if len(cells) > 2 else ""
    if not clue:
        return None
    return {
        "format": "emote",
        "tier": tier,
        "clue_text": clue,
        "clue_text_lower": clue.lower(),
        "items": items,
        "location": location,
    }


def _row_cipher(cells: list[dict], tier: str) -> dict | None:
    cipher = cells[0]["text"]
    decoded = cells[1]["text"] if len(cells) > 1 else ""
    location = cells[2]["text"] if len(cells) > 2 else ""
    if not cipher:
        return None
    return {
        "format": "cipher",
        "tier": tier,
        "clue_text": cipher,
        "clue_text_lower": cipher.lower(),
        "decoded": decoded,
        "location": location,
    }


def _clean_alt(s: str) -> str:
    return html.unescape(s).strip()


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _match_clues(query: str, entries: list[dict]) -> tuple[str, object]:
    q = query.strip().lower()
    if not q:
        return ("none", None)

    exact = [e for e in entries if e["clue_text_lower"] == q]
    if exact:
        return ("exact", exact[0])

    contains = [e for e in entries if q in e["clue_text_lower"]]
    if contains:
        contains.sort(key=lambda e: abs(len(e["clue_text_lower"]) - len(q)))
        return ("did_you_mean", contains[:5])

    return ("none", None)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_solution(entry: dict, wiki_label: str, game: str) -> str:
    fmt = entry["format"]
    base = f"{WIKI_BASE_URLS[game]}{_PAGES[game][fmt].replace(' ', '_')}"
    header = f"**{entry['clue_text']}** ({wiki_label} Wiki — {entry['tier'].capitalize()} {fmt})"
    lines = [header, base, ""]

    if fmt in ("anagram", "cryptic"):
        if entry.get("solution"):
            lines.append(f"**Solution:** {entry['solution']}")
        if entry.get("location"):
            lines.append(f"**Location:** {entry['location']}")
    elif fmt == "emote":
        if entry.get("items"):
            lines.append(f"**Items required:** {entry['items']}")
        if entry.get("location"):
            lines.append(f"**Location:** {entry['location']}")
    elif fmt == "cipher":
        if entry.get("decoded"):
            lines.append(f"**Decoded:** {entry['decoded']}")
        if entry.get("location"):
            lines.append(f"**Location:** {entry['location']}")

    return "\n".join(lines)


def _render_did_you_mean(candidates: list[dict], wiki_label: str) -> str:
    lines = [f"Did you mean one of these clues? ({wiki_label} Wiki)", ""]
    for e in candidates:
        clue = e["clue_text"]
        if len(clue) > 100:
            clue = clue[:97] + "…"
        lines.append(f"- *{clue}* ({e['tier'].capitalize()} {e['format']})")
    lines.append("")
    lines.append("Re-invoke `solve_clue` with the exact clue text to fetch the solution.")
    return "\n".join(lines)
