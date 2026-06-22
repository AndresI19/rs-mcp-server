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

from ._http import MW_BASE_PARAMS, SEARCH_RESULT_LIMIT, WIKI_BASE_URLS


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


def clean_wikitext(s: str) -> str:
    """Strip the common wiki markup: ``[[links]]``, ``{{templates}}``, ``<tags>``."""
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
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
