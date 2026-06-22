"""get_item_recipe tool — RuneScape Wiki recipe templates (Infobox Recipe on RS3, Recipe on OSRS)."""
import re
from collections.abc import Iterator

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, WIKI_LABELS
from ._http import http_get
from ._wiki_parsing import find_template, parse_template_fields as _parse_fields

_TTL = 3600

_TEMPLATES = ("Infobox Recipe", "Recipe")


@instrument("get_item_recipe")
async def get_item_recipe(item_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."
    if not item_name.strip():
        return "No item name provided."

    cache_key = f"recipe:{game}:{item_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = WIKI_LABELS[game]
    canonical = item_name[:1].upper() + item_name[1:]

    params = {
        "action": "query",
        "titles": canonical,
        "prop": "revisions|info",
        "rvprop": "content",
        "rvslots": "main",
        "inprop": "url",
        "redirects": 1,
        **MW_BASE_PARAMS,
    }
    data = await http_get(WIKI_APIS[game], params=params)
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        result = f"Recipe for '{item_name}' not found on the {wiki_label} wiki."
        cache.set(cache_key, result, _TTL)
        return result

    page = pages[0]
    title = page.get("title", canonical)
    url = f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}"
    content = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")

    body = _find_recipe_template(content)
    if body is None:
        result = (
            f"**{title}** ({wiki_label} Wiki)\n{url}\n\n"
            f"No recipe template found on this page — it may not be craftable."
        )
        cache.set(cache_key, result, _TTL)
        return result

    fields = _parse_fields(body)
    result = _format_recipe(title, url, wiki_label, fields)
    cache.set(cache_key, result, _TTL)
    return result


def _find_recipe_template(wikitext: str) -> str | None:
    """Return the body of the first {{Infobox Recipe}} or {{Recipe}} template, or None."""
    for name in ("Infobox Recipe", "Recipe"):
        body = find_template(wikitext, name)
        if body is not None:
            return body
    return None


def _clean(s: str) -> str:
    """Strip wiki [[link]] markup so material names render plainly."""
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _format_recipe(title: str, url: str, wiki_label: str, fields: dict) -> str:
    lines = [f"**{title}** ({wiki_label} Wiki)", url, ""]

    skills = list(_enumerate_skills(fields))
    if skills:
        lines.append("**Skills required:**")
        for level, name, exp, boostable in skills:
            parts = [f"  Level {level} {name}"]
            extras = []
            if exp:
                extras.append(f"{exp} xp")
            if boostable.lower() == "yes":
                extras.append("boostable")
            if extras:
                parts.append(f"({', '.join(extras)})")
            lines.append(" ".join(parts))
        lines.append("")

    mats = list(_enumerate_materials(fields))
    if mats:
        lines.append("**Materials:**")
        for name, qty in mats:
            prefix = f"{qty} " if qty else ""
            lines.append(f"  {prefix}{name}")
        lines.append("")

    achievements = [_clean(fields[f"achievement{i}"]) for i in _enumerate_index("achievement", fields)]
    if achievements:
        lines.append(f"**Achievement:** {', '.join(achievements)}")

    if "tools" in fields:
        lines.append(f"**Tools:** {_clean(fields['tools'])}")
    if "facilities" in fields:
        lines.append(f"**Facilities:** {_clean(fields['facilities'])}")
    if "members" in fields:
        lines.append(f"**Members:** {_clean(fields['members'])}")
    if "ticks" in fields:
        lines.append(f"**Time:** {fields['ticks']} ticks")

    outputs = list(_enumerate_outputs(fields))
    if outputs:
        if len(outputs) == 1 and not outputs[0][1]:
            lines.append("")
            lines.append(f"**Output:** {outputs[0][0]}")
        else:
            lines.append("")
            lines.append("**Outputs:**")
            for name, qty in outputs:
                prefix = f"{qty} " if qty else ""
                lines.append(f"  {prefix}{name}")

    return "\n".join(lines)


def _enumerate_index(prefix: str, fields: dict[str, str]) -> Iterator[int]:
    """Yield the present numeric indices for ``prefix`` (mat1, mat2, …) in order.

    Scans for all matching keys instead of counting up from 1, so a template with
    a gap (e.g. mat1, mat3 after an editor removed mat2) isn't truncated at the gap.
    """
    indices = [
        int(key[len(prefix):])
        for key in fields
        if key.startswith(prefix) and key[len(prefix):].isdigit()
    ]
    yield from sorted(indices)


def _enumerate_skills(fields: dict[str, str]) -> Iterator[tuple[str, str, str, str]]:
    for i in _enumerate_index("skill", fields):
        name = _clean(fields[f"skill{i}"])
        level = fields.get(f"skill{i}lvl", "")
        exp = fields.get(f"skill{i}exp", "")
        boostable = fields.get(f"skill{i}boostable", "")
        yield level, name, exp, boostable


def _enumerate_materials(fields: dict[str, str]) -> Iterator[tuple[str, str]]:
    for i in _enumerate_index("mat", fields):
        name = _clean(fields[f"mat{i}"])
        qty = fields.get(f"mat{i}quantity", "")
        yield name, qty


def _enumerate_outputs(fields: dict[str, str]) -> Iterator[tuple[str, str]]:
    for i in _enumerate_index("output", fields):
        name = _clean(fields[f"output{i}"])
        qty = fields.get(f"output{i}quantity", "")
        yield name, qty
