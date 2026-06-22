"""search_wiki tool — RuneScape Wiki MediaWiki API.

Two-step flow: search for the matching page title via action=query, then fetch
the rendered HTML body via action=parse so transcluded templates (set bonuses,
passive effects, etc.) appear in results. Falls back to alias-substituted
queries (gauntlets→melee gloves, helm→helmet) when the initial search misses.
"""
from html.parser import HTMLParser

import httpx

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._aliases import expand_aliases
from ._constants import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, WIKI_LABELS
from ._http import http_get
from ._wiki_parsing import join_text

_TTL = 3600  # 1 hour
_MAX_EXTRACT_CHARS = 1500


@instrument("search_wiki")
async def search_wiki(query: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not query.strip():
        return "Please provide a search query."

    cache_key = f"wiki:{game}:{query}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = WIKI_LABELS[game]

    title = await _find_title(query, game)
    if title is None:
        for alt in expand_aliases(query)[1:]:
            title = await _find_title(alt, game)
            if title is not None:
                break

    if title is None:
        return f"No results found for '{query}' on the {wiki_label} wiki."

    body = await _fetch_rendered_body(title, game)
    url = f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}"

    if not body:
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\nNo summary available."
    else:
        if len(body) > _MAX_EXTRACT_CHARS:
            body = body[:_MAX_EXTRACT_CHARS].rsplit("\n", 1)[0] + "\n..."
        result = f"**{title}** ({wiki_label} Wiki)\n{url}\n\n{body}"

    cache.set(cache_key, result, _TTL)
    return result


async def _find_title(query: str, game: str) -> str | None:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 1,
        "prop": "info",
        "inprop": "url",
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS[game], params=params)
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    title = pages[0].get("title") or None
    return title


async def _fetch_rendered_body(title: str, game: str) -> str:
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "disableeditsection": 1,
        "redirects": 1,
        **MW_BASE_PARAMS,
    }
    try:
        data = await http_get(WIKI_APIS[game], params=params)
    except httpx.HTTPError:
        return ""
    if "error" in data:
        return ""
    html_text = data.get("parse", {}).get("text") or ""
    return _extract_prose_from_html(html_text)


class _ProseParser(HTMLParser):
    """Collect <h2>/<h3>/<p> text from rendered wiki HTML in document order.

    Set-bonus and passive-effect templates render to <p>, so this captures them;
    headings stay so the reader sees the structure. Infoboxes (<table>) and
    navboxes (<div>) contribute no <p>/<h2>/<h3> text, so they fall away.

    Using html.parser instead of a regex avoids two failure modes the old
    `<(h2|h3|p)[^>]*>(.*?)</\\1>` scan had: attribute values containing '>'
    (mis-split at the inner '>') and spurious spaces where inline tags abut
    punctuation (regex replaced each tag with a space → "unsired ." not "unsired.").
    """

    _PREFIX = {"h2": "## ", "h3": "### ", "p": ""}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[str] = []
        self._tag: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        # Top-level target only; nested inline tags (<a>, <b>, …) just contribute data.
        if tag in self._PREFIX and self._tag is None:
            self._tag = tag
            self._buf = []

    def handle_data(self, data):
        if self._tag is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == self._tag:
            self._flush()

    def _flush(self) -> None:
        if self._tag is None:
            return
        text = join_text(self._buf)
        if text:
            prefix = self._PREFIX[self._tag]
            self.pieces.append(f"\n{prefix}{text}" if prefix else text)
        self._tag = None
        self._buf = []


def _extract_prose_from_html(html_text: str) -> str:
    """Extract section headings + paragraph prose from rendered HTML, skipping chrome."""
    parser = _ProseParser()
    parser.feed(html_text)
    parser._flush()  # flush a trailing tag the source left unclosed
    return "\n".join(parser.pieces).strip()
