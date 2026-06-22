"""Shared wikitext-parsing helpers for the wiki-backed tools.

These pure wikitext helpers were previously copy-pasted across achievements.py,
monsters.py, equipment.py, quests.py, and recipes.py. They are centralized here so
the parsing behavior has a single source of truth; the tool modules import them
under their existing private names so call sites are unchanged. (HTTP-fetching
helpers stay in each module so the test suite can monkeypatch ``http_get`` locally.)
"""
import re


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
