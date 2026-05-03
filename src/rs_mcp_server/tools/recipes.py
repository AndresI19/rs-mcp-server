"""get_item_recipe tool — RuneScape Wiki recipe templates (Infobox Recipe on RS3, Recipe on OSRS)."""
import re

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._http import MW_BASE_PARAMS, WIKI_APIS, WIKI_BASE_URLS, http_get

_TTL = 3600

_TEMPLATES = ("Infobox Recipe", "Recipe")


@instrument("get_item_recipe")
async def get_item_recipe(item_name: str, game: str = "rs3") -> str:
    game = game.lower()
    if game not in WIKI_APIS:
        return f"Unknown game '{game}'. Use 'rs3' or 'osrs'."

    cache_key = f"recipe:{game}:{item_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = "RS3" if game == "rs3" else "OSRS"
    canonical = item_name[:1].upper() + item_name[1:] if item_name else item_name

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
    """Locate the first {{Infobox Recipe}} or {{Recipe}} template; return its body or None."""
    match = re.search(r"\{\{(?:Infobox Recipe|Recipe)\b", wikitext, re.IGNORECASE)
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


def _parse_fields(body: str) -> dict[str, str]:
    """Split on `\\n|` (not bare `|`) so nested-template separators don't fragment values."""
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


def _enumerate_index(prefix: str, fields: dict):
    i = 1
    while f"{prefix}{i}" in fields:
        yield i
        i += 1


def _enumerate_skills(fields: dict):
    for i in _enumerate_index("skill", fields):
        name = _clean(fields[f"skill{i}"])
        level = fields.get(f"skill{i}lvl", "")
        exp = fields.get(f"skill{i}exp", "")
        boostable = fields.get(f"skill{i}boostable", "")
        yield level, name, exp, boostable


def _enumerate_materials(fields: dict):
    for i in _enumerate_index("mat", fields):
        name = _clean(fields[f"mat{i}"])
        qty = fields.get(f"mat{i}quantity", "")
        yield name, qty


def _enumerate_outputs(fields: dict):
    for i in _enumerate_index("output", fields):
        name = _clean(fields[f"output{i}"])
        qty = fields.get(f"output{i}quantity", "")
        yield name, qty
