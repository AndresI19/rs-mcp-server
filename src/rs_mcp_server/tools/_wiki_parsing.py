"""Shared wikitext-parsing helpers for the wiki-backed tools.

These pure wikitext helpers were previously copy-pasted across achievements.py,
monsters.py, equipment.py, quests.py, and recipes.py. They are centralized here so
the parsing behavior has a single source of truth; the tool modules import them
under their existing private names so call sites are unchanged. (HTTP-fetching
helpers stay in each module so the test suite can monkeypatch ``http_get`` locally.)
"""
import html
import re
from collections.abc import Callable

from ._constants import MW_BASE_PARAMS, SEARCH_RESULT_LIMIT, WIKI_BASE_URLS


def titles_match(a: str, b: str) -> bool:
    """Case- and whitespace-insensitive title equality (casefold handles Unicode)."""
    return a.strip().casefold() == b.strip().casefold()


def find_template(wikitext: str, name: str) -> str | None:
    """Return the body of the ``{{name|...}}`` template, or None if absent.

    Walks balanced ``{{``/``}}`` pairs so nested templates inside the body don't
    end the match early. Requires a real delimiter (whitespace, ``|``, or ``}``)
    after the name so e.g. "Infobox Achievement" doesn't match "Infobox
    Achievement category".
    """
    pattern = r"\{\{" + re.escape(name) + r"(?=\s*[|}])"
    match = re.search(pattern, wikitext, re.IGNORECASE)
    if not match:
        return None
    i = match.end()
    depth = 2
    while i < len(wikitext) and depth > 0:
        if wikitext[i:i + 2] == "{{":
            depth += 2
            i += 2
        elif wikitext[i:i + 2] == "}}":
            depth -= 2
            i += 2
        else:
            i += 1
    if depth != 0:
        return None
    return wikitext[match.end():i - 2]


def parse_template_fields(body: str) -> dict[str, str]:
    """Parse a template body into ``{lowercased key: value}``.

    Splits on newline-pipe boundaries so values may contain ``|`` inside links
    or nested templates without being mistaken for new fields.
    """
    fields: dict[str, str] = {}
    parts = re.split(r"\n\s*\|", "\n|" + body)
    for part in parts[1:]:
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        key = name.strip().lower()
        value = value.strip()
        if value:
            fields[key] = value
    return fields


def _strip_templates(s: str) -> str:
    """Remove balanced ``{{…}}`` spans, including nested ones.

    A regex like ``\\{\\{[^}]*\\}\\}`` stops at the first ``}}`` and so leaves a
    trailing ``}}`` on a nested template ({{a|{{b}}}}); walking brace depth removes
    the whole span instead.
    """
    out: list[str] = []
    depth = 0
    i = 0
    while i < len(s):
        if s[i:i + 2] == "{{":
            depth += 1
            i += 2
        elif s[i:i + 2] == "}}" and depth > 0:
            depth -= 1
            i += 2
        else:
            if depth == 0:
                out.append(s[i])
            i += 1
    return "".join(out)


def clean_wikitext(s: str) -> str:
    """Strip common wiki markup: ``[[links]]``, ``{{templates}}`` (incl. nested), ``<tags>``."""
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = _strip_templates(s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r" {2,}", " ", s)  # collapse runs of spaces left where templates were removed
    return s.strip()


def collapse_whitespace(s: str) -> str:
    """Unescape HTML entities and collapse runs of whitespace to single spaces.

    Used by the html.parser-based tools to normalize text extracted from cells.
    """
    return " ".join(html.unescape(s).split())


def disambiguate(name: str, url: str, wiki_label: str, tool: str, param: str, noun: str) -> str:
    """Render the shared "Did you mean …" message when a lookup lands on a near match.

    ``tool``/``param``/``noun`` tailor the re-invoke hint per tool (e.g.
    ``get_achievement``/``name``/``info``).
    """
    return (
        f'Did you mean **"{name}"** ({wiki_label} Wiki)?\n'
        f"{url}\n\n"
        f'Re-invoke `{tool}` with {param}="{name}" to fetch the {noun}.'
    )


def search_params(search_term: str) -> dict:
    """MediaWiki ``generator=search`` params that fetch candidate pages with content.

    The caller issues the request with its own ``http_get`` (so unit tests can
    monkeypatch it per module); this only builds the shared parameter dict.
    """
    return {
        "action": "query",
        "generator": "search",
        "gsrsearch": search_term,
        "gsrlimit": SEARCH_RESULT_LIMIT,
        "prop": "revisions|info",
        "rvprop": "content",
        "rvslots": "main",
        "inprop": "url",
        **MW_BASE_PARAMS,
    }


def first_matching_page(data: dict, game: str, matches: Callable[[str], bool]) -> dict | None:
    """Return the first search result whose wikitext satisfies ``matches`` — the
    type-filter that stops generically-named hits from being returned."""
    for page in data.get("query", {}).get("pages", []):
        revisions = page.get("revisions") or []
        if not revisions:
            continue
        content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
        if not matches(content):
            continue
        title = page.get("title", "")
        return {
            "title": title,
            "url": f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}",
            "content": content,
        }
    return None


def fetch_page_params(title: str, follow_redirects: bool) -> dict:
    """Params for a direct MediaWiki title lookup (page wikitext + canonical URL).

    The caller issues the request with its own ``http_get`` so unit tests can
    monkeypatch it per module; this only builds the shared parameter dict.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions|info",
        "rvprop": "content",
        "rvslots": "main",
        "inprop": "url",
        **MW_BASE_PARAMS,
    }
    if follow_redirects:
        params["redirects"] = 1
    return params


def parse_page_response(data: dict, title: str, game: str) -> dict | None:
    """Extract ``{title, url, content}`` from a query=revisions response.

    Returns None when the page is missing or carries no revision content.
    """
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    revisions = pages[0].get("revisions") or []
    if not revisions:
        return None
    content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
    resolved_title = pages[0].get("title", title)
    return {
        "title": resolved_title,
        "url": f"{WIKI_BASE_URLS[game]}{resolved_title.replace(' ', '_')}",
        "content": content,
    }


class TableScope:
    """Shared <table> nesting tracker for the html.parser table walkers.

    Each walker calls ``open_table``/``close_table`` on <table> start/end and
    guards its tr/td/th handling with ``at_target_level()``. This keeps the depth
    bookkeeping — which makes a table nested inside a cell get ignored rather than
    corrupt the row stream — in one place; each walker still owns its cell capture.

    ``is_target(class_list)`` selects which table to enter; ``first_only`` stops
    after the first match so later tables on the page are ignored.
    """

    def __init__(self, is_target: Callable[[list[str]], bool], first_only: bool = False) -> None:
        self._is_target = is_target
        self._first_only = first_only
        self.depth = 0
        self.in_target = False
        self._target_depth = 0
        self._done = False

    def open_table(self, attrs: dict) -> bool:
        """Register a <table> open; return True if it is the newly-entered target."""
        self.depth += 1
        if (not self.in_target and not self._done
                and self._is_target((attrs.get("class") or "").split())):
            self.in_target = True
            self._target_depth = self.depth
            return True
        return False

    def close_table(self) -> bool:
        """Register a </table>; return True if the target table just closed."""
        closed = self.in_target and self.depth == self._target_depth
        if closed:
            self.in_target = False
            if self._first_only:
                self._done = True
        self.depth -= 1
        return closed

    def at_target_level(self) -> bool:
        """True when inside the target table at its own nesting level (not a nested one)."""
        return self.in_target and self.depth == self._target_depth


def match_by_name(query: str, items: list[dict], key: str) -> tuple[str, object]:
    """Exact-then-substring match on ``items[key]`` (which must be pre-lowercased).

    Returns ``(kind, payload)``: ``("exact", item)``, ``("did_you_mean", up to 5
    substring hits sorted by length-closeness to the query)``, or ``("none", None)``.
    Callers wanting fuzzy/secondary tiers layer them on a ``"none"`` result.
    """
    q = query.strip().lower()
    if not q:
        return ("none", None)
    exact = [it for it in items if it[key] == q]
    if exact:
        return ("exact", exact[0])
    contains = [it for it in items if q in it[key]]
    if contains:
        contains.sort(key=lambda it: abs(len(it[key]) - len(q)))
        return ("did_you_mean", contains[:5])
    return ("none", None)


def render_variants(variants: list[dict], wiki_label: str, base_name: str, tool: str) -> str:
    """Render the 'multiple tiered variants' list shared by the roman-numeral lookups
    (e.g. achievements, quests). ``tool`` tailors the re-invoke hint."""
    lines = [f'Multiple tiered variants of **"{base_name}"** found ({wiki_label} Wiki):', ""]
    for v in variants:
        lines.append(f"- **{v['title']}** — {v['url']}")
    lines.append("")
    lines.append(f"Re-invoke `{tool}` with the exact tier name to fetch full details.")
    return "\n".join(lines)


def join_text(parts: list[str]) -> str:
    """Join accumulated text fragments and collapse whitespace runs to single spaces.

    The html.parser table/section walkers build up a cell's or heading's text as a
    list of data chunks; this concatenates them and normalises spacing in one step.
    """
    return " ".join("".join(parts).split())


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Build a markdown table (header row, separator, data rows) as a list of lines.

    Shared by the tools that emit ranked tables (alchables, moneymakers) so they
    don't each re-spell the ``| a | b |`` / ``|---|---|`` row construction.
    """
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines
