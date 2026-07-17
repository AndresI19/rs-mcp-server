"""solve_clue tool — RuneScape Wiki Treasure Trails clue databases.

Text formats (anagram, cryptic, emote, cipher, challenge, simple) fetch live: each is one
wiki page per game, walked h3+table in document order into a flat index of
{tier, format, clue_text, ...} for exact/fuzzy lookup. Challenge scrolls are tier-less.
Coordinate and visual types (map, puzzle, compass, scan, hot/cold, …) resolve from baked
resources instead — see the coordinate resolver and visual-clue routing below.
"""

import html
import json
import re
from functools import lru_cache
from html.parser import HTMLParser
from importlib import resources

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import *
from ._http import http_get
from ._registry import ToolSpec, game_param, normalize_game, object_schema, register
from ._wiki_parsing import TableScope, collapse_whitespace as _collapse, join_text, match_by_name

_FORMATS = ("anagram", "cryptic", "emote", "cipher", "challenge", "simple")
_TIERS = ("beginner", "easy", "medium", "hard", "elite", "master")

# Formats whose wiki page is a single flat table with no per-tier <h3> sections.
_TIERLESS_FORMATS = frozenset({"challenge"})

# Per-game page titles. None = not supported on this game (returns a polite message).
_PAGES = {
    "osrs": {
        "anagram": "Treasure Trails/Guide/Anagrams",
        "cryptic": "Treasure Trails/Guide/Cryptic clues",
        "emote": "Treasure Trails/Guide/Emote clues",
        "cipher": "Treasure Trails/Guide/Ciphers",
        "challenge": "Treasure Trails/Guide/Challenge scrolls",
        "simple": None,  # OSRS has no separate simple-clue dataset
    },
    "rs3": {
        "anagram": "Treasure Trails/Guide/Anagrams",
        "cryptic": "Treasure Trails/Guide/Cryptics",
        "emote": "Treasure Trails/Guide/Emotes",
        "cipher": None,  # RS3 doesn't have ciphers as a clue format
        "challenge": "Treasure Trails/Guide/Challenge scrolls",
        "simple": "Treasure Trails/Guide/Simple clues",
    },
}


# Coordinate normalization — shared by the offline data generator and the runtime
# resolver so a generated key and a query key are always produced identically.

_COORD_RE = re.compile(
    r"(\d{1,2})\s*degrees?\s*(\d{1,2})\s*minutes?\s*(north|south)"
    r"[,\s]+(\d{1,2})\s*degrees?\s*(\d{1,2})\s*minutes?\s*(east|west)",
    re.IGNORECASE,
)


def normalize_coordinate(text: str) -> str | None:
    """Parse a coordinate clue ("04 degrees 13 minutes south, 16 degrees 25 minutes
    east") into the canonical short-form key "04.13S,16.25E", or None if not a coordinate."""
    m = _COORD_RE.search(text)
    if not m:
        return None
    d1, m1, ns, d2, m2, ew = m.groups()
    return f"{int(d1):02d}.{int(m1):02d}{ns[0].upper()},{int(d2):02d}.{int(m2):02d}{ew[0].upper()}"


@instrument("solve_clue")
async def solve_clue(
    clue_text: str,
    game: str = "rs3",
    clue_format: str | None = None,
    tier: str | None = None,
) -> str:
    game, err = normalize_game(game, WIKI_APIS)
    if err:
        return err
    if not clue_text.strip():
        return "No clue text provided."
    if clue_format is not None:
        clue_format = clue_format.lower()
        if clue_format not in _FORMATS and clue_format != "coordinate":
            valid = ", ".join((*_FORMATS, "coordinate"))
            return f"Unknown clue_format '{clue_format}'. Use one of: {valid}."
    if tier is not None:
        tier = tier.lower()
        if tier not in _TIERS:
            return f"Unknown tier '{tier}'. Use one of: {', '.join(_TIERS)}."

    wiki_label = WIKI_LABELS[game]

    # 1) Coordinate clues resolve from the baked dataset — no network, instant.
    if clue_format in (None, "coordinate"):
        coord = _resolve_coordinate(clue_text, game, wiki_label)
        if coord is not None:
            return coord
        if clue_format == "coordinate":
            return (
                f"'{clue_text}' is not a recognizable coordinate. Expected e.g. "
                "'04 degrees 13 minutes south, 16 degrees 25 minutes east'."
            )

    # 2) Live text formats (anagram / cryptic / emote / cipher / challenge).
    if clue_format is not None and clue_format != "coordinate":
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

    if entries:
        kind, payload = _match_clues(clue_text, entries)
        if kind == "exact":
            return _render_solution(payload, wiki_label, game)
        if kind == "did_you_mean":
            return _render_did_you_mean(payload, wiki_label)

    # 3) Visual/interactive types can't be text-solved — identify and link the guide.
    visual = _detect_visual(clue_text, game)
    if visual is not None:
        return _render_visual(*visual, wiki_label)

    # 4) Nothing matched.
    return (
        f"No matching clue found for '{clue_text}' on the {wiki_label} wiki. "
        f"Browse the full clue lists at {WIKI_BASE_URLS[game]}Treasure_Trails."
    )


# Loaders


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
        cache.set(cache_key, [], TTL_HOUR)
        return []

    entries = _parse_clue_html(text, fmt)
    cache.set(cache_key, entries, TTL_HOUR)
    return entries


# HTML parser (one walker, format-aware row extraction)


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

    Heading text sets the current tier; each 2+-column data row becomes an entry via the
    format-specific _row_to_entry. Table depth is tracked so a table nested in a cell is
    ignored; image alt text is captured per cell so emote item icons survive.
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
        self._scope = TableScope(lambda cls: "wikitable" in cls)
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
            self._scope.open_table(ad)
        elif self._scope.at_target_level():
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
        elif self._scope.at_target_level() and self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag == self._heading:
            self._apply_heading()
            self._heading = None
        elif tag == "table":
            self._scope.close_table()
        elif self._scope.at_target_level():
            if tag == "td" and self._cell is not None and self._row is not None:
                self._row.append(_finalize_cell(self._cell))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                self._emit_row()
                self._row = None

    def _apply_heading(self) -> None:
        text = join_text(self._heading_buf)
        tier = _tier_from_heading(text)
        if tier:
            self.current_tier = tier
        elif self._heading == "h2" and self._heading_id.lower() in self._EXCLUDE_IDS:
            self.current_tier = ""  # leaving the data section

    def _emit_row(self) -> None:
        tierless = self.fmt in _TIERLESS_FORMATS
        if self._row_has_th or len(self._row) < 2 or (not tierless and not self.current_tier):
            return
        entry = _row_to_entry(self._row, self.fmt, self.current_tier)
        if entry is not None:
            self.entries.append(entry)


def _finalize_cell(cell: dict) -> dict:
    text = _collapse(cell["text"])
    items = ", ".join(_clean_alt(a) for a in cell["alts"]) if cell["alts"] else text
    return {"text": text, "items": items}


# Format-specific row extraction

# RS3 anagram pages prefix every clue with this verbose intro; strip it.
_ANAGRAM_PREFIX = re.compile(r"^this anagram reveals who to speak to next:?\s*", re.IGNORECASE)

# Clue-table column layout: 0 = clue text, 1 = the answer (solution / decoded text /
# emote items, by format), 2 = location.
_CLUE_COL, _ANSWER_COL, _LOCATION_COL = 0, 1, 2

# Challenge-scroll layout differs: 0 = NPC who asks, 1 = the question (the clue text
# the player reads), 2 = the answer.
_CHALLENGE_NPC, _CHALLENGE_QUESTION, _CHALLENGE_ANSWER = 0, 1, 2


# Every format except "challenge" is the same clue | answer | location row, differing only in
# what the answer is called, which cell field holds it, and (anagrams only) a clue preamble to
# strip. As data, a new format is one line here instead of a near-copy of the extractor.
#   format → (answer key, cell field to read, prefix to strip from the clue)
_STANDARD_ROWS: dict[str, tuple[str, str, re.Pattern[str] | None]] = {
    "anagram": ("solution", "text", _ANAGRAM_PREFIX),
    "cryptic": ("solution", "text", None),
    "emote": ("items", "items", None),
    "cipher": ("decoded", "text", None),
    # RS3 "simple" clues share the cryptic shape exactly.
    "simple": ("solution", "text", None),
}


def _row_standard(cells: list[dict], tier: str, fmt: str) -> dict | None:
    answer_key, answer_field, strip_prefix = _STANDARD_ROWS[fmt]

    clue = cells[_CLUE_COL]["text"]
    if strip_prefix is not None:
        clue = strip_prefix.sub("", clue).strip()
    if not clue:
        return None

    return {
        "format": fmt,
        "tier": tier,
        "clue_text": clue,
        "clue_text_lower": clue.lower(),
        answer_key: cells[_ANSWER_COL][answer_field] if len(cells) > _ANSWER_COL else "",
        "location": cells[_LOCATION_COL]["text"] if len(cells) > _LOCATION_COL else "",
    }


def _row_challenge(cells: list[dict], tier: str) -> dict | None:
    """Challenge scrolls are the one format with a different layout: NPC | question | answer."""
    question = cells[_CHALLENGE_QUESTION]["text"] if len(cells) > _CHALLENGE_QUESTION else ""
    answer = cells[_CHALLENGE_ANSWER]["text"] if len(cells) > _CHALLENGE_ANSWER else ""
    npc = cells[_CHALLENGE_NPC]["text"]
    if not question:
        return None
    return {
        "format": "challenge",
        "tier": tier,  # challenge pages have no tier sections → ""
        "clue_text": question,
        "clue_text_lower": question.lower(),
        "answer": answer,
        "npc": npc,
    }


def _row_to_entry(cells: list[dict], fmt: str, tier: str) -> dict | None:
    if fmt == "challenge":
        return _row_challenge(cells, tier)
    if fmt in _STANDARD_ROWS:
        return _row_standard(cells, tier, fmt)
    return None


def _clean_alt(s: str) -> str:
    return html.unescape(s).strip()


# Matching


def _match_clues(query: str, entries: list[dict]) -> tuple[str, object]:
    return match_by_name(query, entries, "clue_text_lower")


# Rendering

# Per-format solution fields (label, entry-key), rendered in order when present.
_SOLUTION_FIELDS = {
    "anagram": (("Solution", "solution"), ("Location", "location")),
    "cryptic": (("Solution", "solution"), ("Location", "location")),
    "emote": (("Items required", "items"), ("Location", "location")),
    "cipher": (("Decoded", "decoded"), ("Location", "location")),
    "challenge": (("Answer", "answer"), ("Asked by", "npc")),
    "simple": (("Solution", "solution"), ("Location", "location")),
}


def _render_solution(entry: dict, wiki_label: str, game: str) -> str:
    fmt = entry["format"]
    base = f"{WIKI_BASE_URLS[game]}{_PAGES[game][fmt].replace(' ', '_')}"
    tier_word = f"{entry['tier'].capitalize()} " if entry["tier"] else ""
    header = f"**{entry['clue_text']}** ({wiki_label} Wiki — {tier_word}{fmt})"
    lines = [header, base, ""]
    for label, key in _SOLUTION_FIELDS.get(fmt, ()):
        if entry.get(key):
            lines.append(f"**{label}:** {entry[key]}")
    return "\n".join(lines)


def _render_did_you_mean(candidates: list[dict], wiki_label: str) -> str:
    lines = [f"Did you mean one of these clues? ({wiki_label} Wiki)", ""]
    for e in candidates:
        clue = e["clue_text"]
        if len(clue) > 100:
            clue = clue[:97] + "…"
        tier_word = f"{e['tier'].capitalize()} " if e["tier"] else ""
        lines.append(f"- *{clue}* ({tier_word}{e['format']})")
    lines.append("")
    lines.append("Re-invoke `solve_clue` with the exact clue text to fetch the solution.")
    return "\n".join(lines)


# Baked resources — coordinate datasets + visual-clue links (no network at runtime)


@lru_cache(maxsize=None)
def _load_json_resource(name: str) -> dict:
    """Load and cache a committed JSON resource from rs_mcp_server/resources/clues/."""
    path = resources.files("rs_mcp_server").joinpath("resources", "clues", name)
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_coordinate(clue_text: str, game: str, wiki_label: str) -> str | None:
    """Resolve a coordinate clue from the baked dataset. Returns None when the query
    isn't a coordinate at all (so the caller falls through to the text formats)."""
    key = normalize_coordinate(clue_text)
    if key is None:
        return None
    coords = _load_json_resource(f"coordinates_{game}.json")["coordinates"]
    entry = coords.get(key)
    if entry is None:
        guide = f"{WIKI_BASE_URLS[game]}Treasure_Trails/Guide/Coordinates"
        return (
            f"Coordinate **{key}** is not in the {wiki_label} dataset "
            f"(it may be a newer clue). Browse all coordinates: {guide}"
        )
    return _render_coordinate(entry, wiki_label)


def _render_coordinate(entry: dict, wiki_label: str) -> str:
    tier_word = f"{entry['tier'].capitalize()} " if entry.get("tier") else ""
    lines = [
        f"**{entry['degrees']}** ({wiki_label} Wiki — {tier_word}coordinate)",
        entry["wiki_url"],
        "",
    ]
    if entry.get("location"):
        lines.append(f"**Location:** {entry['location']}")
    if entry.get("travel"):
        lines.append(f"**Suggested travel:** {entry['travel']}")
    if entry.get("requirements") and entry["requirements"].rstrip(".").lower() != "none":
        lines.append(f"**Requirements:** {entry['requirements']}")
    if entry.get("fight") == "yes":
        lines.append("**Heads up:** the dig spot is guarded — be ready to fight.")
    lines.append("")
    lines.append("The exact dig spot is shown on the map at the link above.")
    return "\n".join(lines)


# Visual/interactive clue types → query keywords that identify them (tool returns the
# matching guide link from visual_clues.json). Order matters: specific types are checked
# before the generic "puzzle" catch-all, so "lockbox" wins over "puzzle box".
_VISUAL_KEYWORDS = {
    "light box": ("light box", "lightbox"),
    "celtic knot": ("celtic", "knot"),
    "lockbox": ("lockbox",),
    "compass": ("compass",),
    "scan": ("scan",),
    "tower": ("tower",),
    "hot cold": ("hot", "cold", "strange device"),
    "map": ("map",),
    "puzzle box": ("puzzle", "sliding"),
}


def _detect_visual(clue_text: str, game: str) -> tuple[str, dict] | None:
    """Identify a visual/interactive clue type from the query, if any is documented
    for this game."""
    q = clue_text.lower()
    available = _load_json_resource("visual_clues.json").get(game, {})
    for vtype, keywords in _VISUAL_KEYWORDS.items():
        if vtype in available and any(kw in q for kw in keywords):
            return vtype, available[vtype]
    return None


def _render_visual(vtype: str, info: dict, wiki_label: str) -> str:
    # Some types are trivially solved in-game, where a wiki lookup adds nothing
    # (e.g. compass — just follow the arrow). Those carry "in_game" and no guide link.
    if info.get("in_game"):
        return f"**{vtype.capitalize()} clue** — {info['blurb']}"
    lines = [
        f"This looks like a **{vtype}** clue ({wiki_label} Wiki).",
        "",
        info["blurb"],
        info["guide_url"],
    ]
    if info.get("image_url"):
        lines.append(info["image_url"])
    return "\n".join(lines)


TOOL = register(
    ToolSpec(
        name="solve_clue",
        description="Look up a RuneScape clue scroll step by its clue text and return the solution (NPC, location, items required, decoded text, answer). Solves the text formats — anagram, cryptic, emote, cipher, challenge-scroll Q&A, and RS3 simple clues — across both games; resolves coordinate clues from a built-in dataset when you pass the degrees (e.g. '04 degrees 13 minutes south, 16 degrees 25 minutes east'); and for visual/interactive clues (maps, puzzle boxes, light boxes, compass, scan, hot/cold, etc.) returns a link to the relevant wiki guide. clue_format and tier are optional hints; without them the tool auto-detects coordinates and searches all text formats. Ciphers are OSRS-only; challenge scrolls and coordinates are not tier-segmented. If the user has not specified which game (RS3 or OSRS), ask them before calling this tool.",
        input_schema=object_schema(
            {
                "clue_text": {
                    "type": "string",
                    "description": "The clue text the player is stuck on — anagram letters, cryptic/challenge riddle, emote instructions, cipher text, or coordinate degrees.",
                },
                "game": game_param("Which game wiki to query: 'rs3' (default) or 'osrs'."),
                "clue_format": {
                    "type": "string",
                    "enum": [
                        "anagram",
                        "cryptic",
                        "emote",
                        "cipher",
                        "challenge",
                        "simple",
                        "coordinate",
                    ],
                    "description": "Optional format hint to narrow the lookup. Ciphers are OSRS-only. Coordinates are auto-detected from the degrees text, so the hint is rarely needed.",
                },
                "tier": {
                    "type": "string",
                    "enum": ["beginner", "easy", "medium", "hard", "elite", "master"],
                    "description": "Optional tier hint to filter results.",
                },
            },
            required=["clue_text"],
        ),
        invoke=lambda args: solve_clue(
            args["clue_text"],
            args.get("game", "rs3"),
            args.get("clue_format"),
            args.get("tier"),
        ),
    )
)
