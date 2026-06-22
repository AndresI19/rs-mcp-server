"""get_game_setting tool — RuneScape Wiki in-game Settings pages.

Parses the rendered Settings page HTML on each game's wiki, walks <h2>/<h3>
headings and <table class="wikitable"> rows to build a name → description index,
then supports exact / substring / fuzzy / description / wiki-search-fallback lookup.
"""
from difflib import get_close_matches
from html.parser import HTMLParser

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import MW_BASE_PARAMS, TTL_HOUR, WIKI_APIS, WIKI_BASE_URLS, WIKI_LABELS
from ._http import http_get
from ._wiki_parsing import TableScope, join_text, match_by_name

_TTL = TTL_HOUR
_PAGE = "Settings"

_SKIP_SECTIONS = {
    "update_history", "history", "changes",
    "gallery", "references", "trivia", "see_also",
    "mw-toc-heading",
}


@instrument("get_game_setting")
async def get_game_setting(setting_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not setting_name.strip():
        return "No setting name provided."

    cache_key = f"settings:{game}"
    rows = cache.get(cache_key)
    if rows is None:
        rows = await _fetch_settings_index(game)
        if rows is None:
            return f"Could not load the Settings page for {game.upper()}."
        cache.set(cache_key, rows, _TTL)

    wiki_label = WIKI_LABELS[game]
    page_url = f"{WIKI_BASE_URLS[game]}{_PAGE}"

    kind, payload = _match_setting(setting_name, rows)
    if kind == "exact":
        return _render_setting(payload, wiki_label, page_url)
    if kind == "did_you_mean":
        return _render_did_you_mean(payload, wiki_label, header="Did you mean one of these settings?")
    if kind == "description_hits":
        return _render_did_you_mean(payload, wiki_label, header=f"No setting named '{setting_name}', but it appears in these descriptions:")

    # All local-index tiers failed — try a wiki-wide search before giving up.
    suggestions = await _wiki_search_fallback(setting_name, game)
    if suggestions:
        return _render_wiki_suggestions(suggestions, wiki_label, setting_name)

    return f"No matching setting for '{setting_name}' on the {wiki_label} wiki. Browse the full list at {page_url}."


# ---------------------------------------------------------------------------
# Wiki fetch
# ---------------------------------------------------------------------------

async def _fetch_settings_index(game: str) -> list[dict] | None:
    params = {
        "action": "parse",
        "page": _PAGE,
        "prop": "text",
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS[game], params=params)
    text = data.get("parse", {}).get("text")
    if not text:
        return None
    return _parse_settings_html(text)


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------

class _SettingsParser(HTMLParser):
    """Walk <h2>/<h3> headings and <table class="wikitable"> rows in document order.

    Replaces a regex that matched <h2|h3|table> blocks then re-split <tr>/<td> with
    '.*?' — fragile on any nested table, and unreadable. html.parser tracks
    section/subsection state and emits one row per 2-column data row; capturing cell
    text via handle_data also drops inner tags without a separate tag-stripping pass.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.section = self.section_anchor = ""
        self.subsection = self.subsection_anchor = ""
        self._heading: str | None = None
        self._heading_id = ""
        self._buf: list[str] = []
        self._capture = False
        self._scope = TableScope(lambda cls: "wikitable" in cls)
        self._cells: list[str] | None = None
        self._row_has_th = False

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag in ("h2", "h3"):
            self._heading = tag
            self._heading_id = ad.get("id", "")
            self._buf = []
            self._capture = True
        elif tag == "table":
            self._scope.open_table(ad)
        elif self._scope.at_target_level():
            if tag == "tr":
                self._cells = []
                self._row_has_th = False
            elif tag == "th":
                self._row_has_th = True
            elif tag == "td" and self._cells is not None:
                self._buf = []
                self._capture = True

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == self._heading:
            text = join_text(self._buf)
            if self._heading == "h2":
                self.section, self.section_anchor = text, self._heading_id
                self.subsection = self.subsection_anchor = ""
            else:
                self.subsection, self.subsection_anchor = text, self._heading_id
            self._heading = None
            self._capture = False
        elif tag == "td" and self._cells is not None and self._capture:
            self._cells.append(join_text(self._buf))
            self._capture = False
        elif tag == "tr" and self._cells is not None:
            self._emit_row()
            self._cells = None
        elif tag == "table":
            self._scope.close_table()

    def _emit_row(self) -> None:
        if self._row_has_th or self._cells is None or len(self._cells) < 2:
            return
        if (self.section_anchor.lower() in _SKIP_SECTIONS
                or self.subsection_anchor.lower() in _SKIP_SECTIONS):
            return
        name, desc = self._cells[0], self._cells[1]
        if not name or not desc:
            return
        self.rows.append({
            "name": name,
            "name_lower": name.lower(),
            "section": self.section,
            "subsection": self.subsection,
            "description": desc,
            "anchor": self.subsection_anchor or self.section_anchor,
        })


def _parse_settings_html(html_text: str) -> list[dict]:
    """Walk h2/h3 headings and wikitable rows in document order into setting rows."""
    parser = _SettingsParser()
    parser.feed(html_text)
    return parser.rows


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _match_setting(query: str, rows: list[dict]) -> tuple[str, object]:
    q = query.strip().lower()
    if not q:
        return ("none", None)

    kind, payload = match_by_name(query, rows, "name_lower")
    if kind != "none":
        return kind, payload

    # Fuzzy match — typo recovery before falling back to description text.
    names = [r["name"] for r in rows]
    close = get_close_matches(query, names, n=5, cutoff=0.7)
    if close:
        by_name = {r["name"]: r for r in rows}
        return ("did_you_mean", [by_name[name] for name in close])

    desc_hits = [r for r in rows if q in r["description"].lower()]
    if desc_hits:
        return ("description_hits", desc_hits[:5])

    return ("none", None)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _section_path(row: dict) -> str:
    if row["section"] and row["subsection"]:
        return f"{row['section']} > {row['subsection']}"
    return row["section"] or row["subsection"] or "—"


def _render_setting(row: dict, wiki_label: str, page_url: str) -> str:
    anchor_part = f"#{row['anchor']}" if row["anchor"] else ""
    lines = [
        f"**{row['name']}** ({wiki_label} Wiki — {_section_path(row)})",
        f"{page_url}{anchor_part}",
        "",
        row["description"],
    ]
    return "\n".join(lines)


def _render_did_you_mean(candidates: list[dict], wiki_label: str, header: str) -> str:
    lines = [f"{header} ({wiki_label} Wiki)", ""]
    for r in candidates:
        desc = r["description"]
        if len(desc) > 120:
            desc = desc[:117] + "…"
        lines.append(f"- **{r['name']}** ({_section_path(r)}) — {desc}")
    lines.append("")
    lines.append("Re-invoke `get_game_setting` with the exact name to fetch full details.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wiki-search fallback (issue #74) — invoked when the local index has no hits
# ---------------------------------------------------------------------------

async def _wiki_search_fallback(query: str, game: str) -> list[dict]:
    """Generic wiki search for queries that don't match any settings-page row."""
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 3,
        "prop": "extracts",
        "explaintext": True,
        "exsentences": 1,
        "exintro": True,
        **MW_BASE_PARAMS,
    }
    try:
        data = await http_get(WIKI_APIS[game], params=params)
    except Exception:
        return []
    pages = (data.get("query") or {}).get("pages") or []
    out: list[dict] = []
    for p in pages:
        title = p.get("title")
        if not title:
            continue
        snippet = (p.get("extract") or "").strip()
        out.append({
            "title": title,
            "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            "snippet": snippet[:160] + ("…" if len(snippet) > 160 else ""),
        })
    return out


def _render_wiki_suggestions(suggestions: list[dict], wiki_label: str, query: str) -> str:
    lines = [
        f"Couldn't find an exact setting for '{query}' on the {wiki_label} Wiki — these pages may help:",
        "",
    ]
    for s in suggestions:
        line = f"- **{s['title']}** — {s['url']}"
        if s["snippet"]:
            line += f"\n    {s['snippet']}"
        lines.append(line)
    return "\n".join(lines)
