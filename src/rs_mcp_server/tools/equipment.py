"""get_equipment_stats tool — RuneScape Wiki Infobox Bonuses (OSRS + RS3)."""

import html
from html.parser import HTMLParser

import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import MW_BASE_PARAMS, TTL_HOUR, WIKI_APIS, WIKI_LABELS
from ._http import http_get
from ._registry import ToolSpec, game_param, normalize_game, object_schema, register
from ._wiki_parsing import (
    clean_wikitext as _clean,
    disambiguate,
    fetch_page_params,
    find_template as _find_template,
    first_matching_page,
    parse_page_response,
    parse_template_fields as _parse_fields,
    render_labeled_fields,
    search_params,
    titles_match as _titles_match,
)

# Section headings whose prose should be surfaced alongside the infobox.
# Each entry is (canonical display label, accepted heading variants — lowercased).
_SECTION_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Set bonus", ("set bonus", "set effect", "set effects")),
    ("Passive", ("passive", "passive effect", "passive effects", "passive ability")),
    ("Special attack", ("special attack", "special attacks")),
    ("Special properties", ("special properties", "special property", "properties")),
)

_SECTION_PROSE_LIMIT = 400

_OSRS_STATS = [
    ("Slot", "slot"),
    ("Combat style", "combatstyle"),
    ("Speed", "speed"),
    ("Attack range", "attackrange"),
    ("Attack stab", "astab"),
    ("Attack slash", "aslash"),
    ("Attack crush", "acrush"),
    ("Attack magic", "amagic"),
    ("Attack ranged", "arange"),
    ("Defence stab", "dstab"),
    ("Defence slash", "dslash"),
    ("Defence crush", "dcrush"),
    ("Defence magic", "dmagic"),
    ("Defence ranged", "drange"),
    ("Strength", "str"),
    ("Ranged strength", "rstr"),
    ("Magic damage", "mdmg"),
    ("Prayer", "prayer"),
]

_RS3_STATS = [
    ("Slot", "slot"),
    ("Class", "class"),
    ("Style", "style"),
    ("Tier", "tier"),
    ("Damage", "damage"),
    ("Accuracy", "accuracy"),
    ("Speed", "speed"),
    ("Attack range", "attack_range"),
    ("Armour", "armour"),
    ("Life points", "life"),
    ("Prayer", "prayer"),
    ("Magic damage", "magic"),
    ("Ranged damage", "ranged"),
    ("Strength", "strength"),
    ("Requirements", "requirements"),
]

_STATS_BY_GAME = {"osrs": _OSRS_STATS, "rs3": _RS3_STATS}


@instrument("get_equipment_stats")
async def get_equipment_stats(item_name: str, game: str = "rs3") -> str:
    game, err = normalize_game(game, WIKI_APIS)
    if err:
        return err
    if not item_name.strip():
        return "No item name provided."

    cache_key = f"equipment:{game}:{item_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = WIKI_LABELS[game]

    result = await _stats_from_direct(item_name, game, wiki_label) or await _stats_from_search(
        item_name, game, wiki_label
    )
    if result is None:
        return f"No equipment found for '{item_name}' on the {wiki_label} wiki."
    return _cache_and_return(result, cache_key)


async def _stats_from_direct(item_name: str, game: str, wiki_label: str) -> str | None:
    """Direct page lookup: render an exact Infobox-Bonuses hit, or disambiguate a near-title."""
    direct = await _fetch_page(item_name, game, follow_redirects=True)
    if direct is None:
        return None
    body = _find_template(direct["content"], "Infobox Bonuses")
    if body is None:
        return None
    if _titles_match(item_name, direct["title"]):
        return await _render_stats(direct, game, wiki_label, body)
    return _disambiguate(direct["title"], direct["url"], wiki_label)


async def _stats_from_search(item_name: str, game: str, wiki_label: str) -> str | None:
    """Search fallback: disambiguate a near-title, else render the hit."""
    candidate = await _search_equipment(item_name, game)
    if candidate is None:
        return None
    if not _titles_match(item_name, candidate["title"]):
        return _disambiguate(candidate["title"], candidate["url"], wiki_label)
    # _search_equipment guarantees the content carries an Infobox Bonuses template.
    body = _find_template(candidate["content"], "Infobox Bonuses")
    return await _render_stats(candidate, game, wiki_label, body)


async def _render_stats(page: dict, game: str, wiki_label: str, body: str) -> str:
    """Format an equipment page's bonuses table plus its named-section prose."""
    sections = await _fetch_named_sections(page["title"], game)
    return _format_stats(
        page["title"], page["url"], wiki_label, _parse_fields(body), _STATS_BY_GAME[game], sections
    )


def _disambiguate(title: str, url: str, wiki_label: str) -> str:
    return disambiguate(title, url, wiki_label, "get_equipment_stats", "item_name", "stats")


def _cache_and_return(value: str, cache_key: str) -> str:
    cache.set(cache_key, value, TTL_HOUR)
    return value


# ---------------------------------------------------------------------------
# Wiki API helpers
# ---------------------------------------------------------------------------


async def _fetch_page(title: str, game: str, follow_redirects: bool) -> dict | None:
    data = await http_get(WIKI_APIS[game], params=fetch_page_params(title, follow_redirects))
    return parse_page_response(data, title, game)


async def _search_equipment(query: str, game: str) -> dict | None:
    data = await http_get(WIKI_APIS[game], params=search_params(query))
    return first_matching_page(
        data, game, lambda c: _find_template(c, "Infobox Bonuses") is not None
    )


def _format_stats(
    title: str,
    url: str,
    wiki_label: str,
    fields: dict[str, str],
    stats_def: list[tuple[str, str]],
    sections: dict[str, str],
) -> str:
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]
    lines += render_labeled_fields(fields, stats_def, _clean)

    for label, _aliases in _SECTION_TARGETS:
        prose = sections.get(label)
        if prose:
            lines.append("")
            lines.append(f"## {label}")
            lines.append(prose)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Named-section prose enrichment (issue #77)
# ---------------------------------------------------------------------------


async def _fetch_named_sections(title: str, game: str) -> dict[str, str]:
    """Fetch the rendered page and extract prose for the target named sections.

    Returns {} on any error — set-bonus prose is enrichment, not core data.
    """
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "redirects": 1,
        **MW_BASE_PARAMS,
    }
    try:
        data = await http_get(WIKI_APIS[game], params=params)
    except httpx.HTTPError:
        return {}
    if "error" in data:
        return {}
    html_text = data.get("parse", {}).get("text") or ""
    return _extract_named_sections(html_text)


class _SectionsParser(HTMLParser):
    """Collect paragraph prose for recognised <h2> sections (set bonus, etc.).

    Walks the rendered page: each <h2> opens a section; if its heading matches a
    target alias (and that label isn't already filled), the following <p> text is
    collected until the next <h2>. Replaces an <h2>-split + <p> regex scan.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: dict[str, str] = {}
        self._label: str | None = None
        self._paragraphs: list[str] = []
        self._in_heading = False
        self._heading = ""
        self._in_p = False
        self._p = ""

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self._flush()
            self._in_heading = True
            self._heading = ""
        elif tag == "p" and self._label is not None:
            self._in_p = True
            self._p = ""

    def handle_data(self, data):
        if self._in_heading:
            self._heading += data
        elif self._in_p:
            self._p += data

    def handle_endtag(self, tag):
        if tag == "h2" and self._in_heading:
            self._in_heading = False
            self._label = self._match(self._heading)
            self._paragraphs = []
        elif tag == "p" and self._in_p:
            self._in_p = False
            text = " ".join(html.unescape(self._p).split())
            if text:
                self._paragraphs.append(text)

    def _match(self, heading: str) -> str | None:
        ht = heading.strip().lower()
        for label, aliases in _SECTION_TARGETS:
            if ht in aliases and label not in self.sections:
                return label
        return None

    def _flush(self) -> None:
        if self._label is not None and self._paragraphs:
            self.sections[self._label] = _truncate(
                "\n\n".join(self._paragraphs), _SECTION_PROSE_LIMIT
            )
        self._label = None
        self._paragraphs = []


def _extract_named_sections(html_text: str) -> dict[str, str]:
    parser = _SectionsParser()
    parser.feed(html_text)
    parser._flush()  # finalize the trailing section
    return parser.sections


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    # Prefer to end at a sentence boundary — trim back to the last period within the
    # limit — falling back to a hard character cut when there's none to trim to.
    cut = s[:limit].rsplit(".", 1)[0]
    return (cut + "." if cut else s[:limit]) + " …"


TOOL = register(
    ToolSpec(
        name="get_equipment_stats",
        description="Get combat-equipment stats for a single item — attack/defence bonuses on OSRS, tier/damage/accuracy on RS3. To compare multiple items, call this tool once per item and tabulate the results.",
        input_schema=object_schema(
            {
                "item_name": {
                    "type": "string",
                    "description": "The exact or approximate item name.",
                },
                "game": game_param("Which game wiki to query: 'rs3' (default) or 'osrs'."),
            },
            required=["item_name"],
        ),
        invoke=lambda args: get_equipment_stats(args["item_name"], args.get("game", "rs3")),
    )
)
