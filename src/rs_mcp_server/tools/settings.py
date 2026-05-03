"""get_game_setting tool — RuneScape Wiki in-game Settings pages.

Parses the rendered Settings page HTML on each game's wiki, walks <h2>/<h3>
headings and <table class="wikitable"> rows to build a name → description index,
then supports exact / fuzzy / description-fallback lookup.
"""
import html
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get

_TTL = 3600
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

    wiki_label = "RS3" if game == "rs3" else "OSRS"
    page_url = f"{WIKI_BASE_URLS[game]}{_PAGE}"

    kind, payload = _match_setting(setting_name, rows)
    if kind == "exact":
        return _render_setting(payload, wiki_label, page_url)
    if kind == "did_you_mean":
        return _render_did_you_mean(payload, wiki_label, header="Did you mean one of these settings?")
    if kind == "description_hits":
        return _render_did_you_mean(payload, wiki_label, header=f"No setting named '{setting_name}', but it appears in these descriptions:")
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

_HEADING_OR_TABLE = re.compile(
    r'<h2[^>]*id="([^"]+)"[^>]*>(.*?)</h2>'
    r'|<h3[^>]*id="([^"]+)"[^>]*>(.*?)</h3>'
    r'|<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>',
    re.DOTALL,
)


def _parse_settings_html(html_text: str) -> list[dict]:
    """Walk h2/h3/table tags in document order, build a flat list of setting rows."""
    rows: list[dict] = []
    section = ""
    section_anchor = ""
    subsection = ""
    subsection_anchor = ""

    for m in _HEADING_OR_TABLE.finditer(html_text):
        h2_id, h2_text, h3_id, h3_text, table_body = m.groups()
        if h2_id is not None:
            section = _strip_tags(h2_text).strip()
            section_anchor = h2_id
            subsection = ""
            subsection_anchor = ""
        elif h3_id is not None:
            subsection = _strip_tags(h3_text).strip()
            subsection_anchor = h3_id
        else:
            if section_anchor.lower() in _SKIP_SECTIONS or subsection_anchor.lower() in _SKIP_SECTIONS:
                continue
            anchor = subsection_anchor or section_anchor
            for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", table_body, re.DOTALL):
                tr_html = tr_match.group(1)
                if "<th" in tr_html:
                    continue
                cells = re.findall(r"<td[^>]*>(.*?)</td>", tr_html, re.DOTALL)
                if len(cells) < 2:
                    continue
                name = _strip_tags(cells[0]).strip()
                desc = _strip_tags(cells[1]).strip()
                if not name or not desc:
                    continue
                rows.append({
                    "name": name,
                    "name_lower": name.lower(),
                    "section": section,
                    "subsection": subsection,
                    "description": desc,
                    "anchor": anchor,
                })
    return rows


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _match_setting(query: str, rows: list[dict]) -> tuple[str, object]:
    q = query.strip().lower()
    if not q:
        return ("none", None)

    exact = [r for r in rows if r["name_lower"] == q]
    if exact:
        return ("exact", exact[0])

    contains = [r for r in rows if q in r["name_lower"]]
    if contains:
        contains.sort(key=lambda r: abs(len(r["name_lower"]) - len(q)))
        return ("did_you_mean", contains[:5])

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
