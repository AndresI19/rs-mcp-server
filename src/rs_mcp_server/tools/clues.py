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

_HEADING_OR_TABLE = re.compile(
    r'<h2[^>]*id="([^"]+)"[^>]*>(.*?)</h2>'
    r'|<h3[^>]*id="([^"]+)"[^>]*>(.*?)</h3>'
    r'|<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>',
    re.DOTALL,
)


def _parse_clue_html(html_text: str, fmt: str) -> list[dict]:
    entries: list[dict] = []
    current_tier = ""

    for m in _HEADING_OR_TABLE.finditer(html_text):
        h2_id, h2_text, h3_id, h3_text, table_body = m.groups()
        if h2_id is not None:
            tier = _tier_from_heading(_strip_tags(h2_text))
            if tier:
                current_tier = tier
            elif h2_id.lower() in {"references", "see_also", "trivia", "gallery"}:
                current_tier = ""  # leaving the data section
        elif h3_id is not None:
            tier = _tier_from_heading(_strip_tags(h3_text))
            if tier:
                current_tier = tier
        else:
            if not current_tier:
                continue
            for cells in _extract_rows(table_body):
                if len(cells) < 2:
                    continue
                entry = _row_to_entry(cells, fmt, current_tier)
                if entry is not None:
                    entries.append(entry)
    return entries


def _tier_from_heading(text: str) -> str:
    t = text.lower()
    for tier in _TIERS:
        if tier in t:
            return tier
    return ""


class _CluesRowParser(HTMLParser):
    """Extract a wikitable body's data rows as per-cell ``{text, items}`` dicts.

    Tracks table depth so a table nested inside a cell is ignored rather than
    mis-split — the previous regex scan stopped at the first ``</tr>``/``</td>``.
    Image ``alt`` text is captured per cell so emote item icons survive.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict]] = []
        self._table_depth = 0
        self._row: list[dict] | None = None
        self._row_has_th = False
        self._cell: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table_depth += 1
            return
        if self._table_depth != 0:
            return
        if tag == "tr":
            self._row = []
            self._row_has_th = False
        elif tag == "th":
            self._row_has_th = True
        elif tag == "td" and self._row is not None:
            self._cell = {"text": "", "alts": []}
        elif tag == "img" and self._cell is not None:
            alt = dict(attrs).get("alt")
            if alt:
                self._cell["alts"].append(alt)

    def handle_data(self, data):
        if self._table_depth == 0 and self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag == "table":
            self._table_depth -= 1
            return
        if self._table_depth != 0:
            return
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(_finalize_cell(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if not self._row_has_th:
                self.rows.append(self._row)
            self._row = None


def _finalize_cell(cell: dict) -> dict:
    text = _collapse(cell["text"])
    items = ", ".join(_clean_alt(a) for a in cell["alts"]) if cell["alts"] else text
    return {"text": text, "items": items}


def _extract_rows(table_body: str) -> list[list[dict]]:
    parser = _CluesRowParser()
    parser.feed(table_body)
    return parser.rows


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


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


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
