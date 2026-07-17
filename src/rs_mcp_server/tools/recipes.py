"""get_item_recipe tool — RuneScape Wiki recipe templates (Infobox Recipe on RS3, Recipe on OSRS)."""

import re
from collections.abc import Iterator

from rs_mcp_server import cache
from rs_mcp_server.logging import instrument

from ._constants import *
from ._http import http_get
from ._registry import ToolSpec, game_param, normalize_game, object_schema, register
from ._wiki_parsing import fetch_page_params, find_template, parse_template_fields as _parse_fields

_TEMPLATES = ("Infobox Recipe", "Recipe")

# Single-value fields rendered as "**Label:** <cleaned value>" when present.
_SIMPLE_FIELDS = (
    ("tools", "Tools"),
    ("facilities", "Facilities"),
    ("members", "Members"),
)


@instrument("get_item_recipe")
async def get_item_recipe(item_name: str, game: str = "rs3") -> str:
    game, err = normalize_game(game, WIKI_APIS)
    if err:
        return err
    if not item_name.strip():
        return "No item name provided."

    cache_key = f"recipe:{game}:{item_name.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    wiki_label = WIKI_LABELS[game]
    canonical = item_name[:1].upper() + item_name[1:]

    data = await http_get(
        WIKI_APIS[game], params=fetch_page_params(canonical, follow_redirects=True)
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return cache.set_and_return(
            cache_key, f"Recipe for '{item_name}' not found on the {wiki_label} wiki.", TTL_HOUR
        )

    page = pages[0]
    title = page.get("title", canonical)
    url = f"{WIKI_BASE_URLS[game]}{title.replace(' ', '_')}"
    content = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")

    body = _find_recipe_template(content)
    if body is None:
        return cache.set_and_return(
            cache_key,
            f"**{title}** ({wiki_label} Wiki)\n{url}\n\n"
            f"No recipe template found on this page — it may not be craftable.",
            TTL_HOUR,
        )

    fields = _parse_fields(body)
    return cache.set_and_return(cache_key, _format_recipe(title, url, wiki_label, fields), TTL_HOUR)


def _find_recipe_template(wikitext: str) -> str | None:
    """Return the body of the first {{Infobox Recipe}} or {{Recipe}} template, or None."""
    for name in _TEMPLATES:
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

    mats = list(_enumerate_pairs("mat", fields))
    if mats:
        lines.append("**Materials:**")
        for name, qty in mats:
            prefix = f"{qty} " if qty else ""
            lines.append(f"  {prefix}{name}")
        lines.append("")

    achievements = [
        _clean(fields[f"achievement{i}"]) for i in _enumerate_index("achievement", fields)
    ]
    if achievements:
        lines.append(f"**Achievement:** {', '.join(achievements)}")

    for key, label in _SIMPLE_FIELDS:
        if key in fields:
            lines.append(f"**{label}:** {_clean(fields[key])}")
    if "ticks" in fields:
        lines.append(f"**Time:** {fields['ticks']} ticks")

    outputs = list(_enumerate_pairs("output", fields))
    if outputs:
        lines.append("")
        if len(outputs) == 1 and not outputs[0][1]:
            lines.append(f"**Output:** {outputs[0][0]}")
        else:
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
        int(key[len(prefix) :])
        for key in fields
        if key.startswith(prefix) and key[len(prefix) :].isdigit()
    ]
    yield from sorted(indices)


def _enumerate_skills(fields: dict[str, str]) -> Iterator[tuple[str, str, str, str]]:
    for i in _enumerate_index("skill", fields):
        name = _clean(fields[f"skill{i}"])
        level = fields.get(f"skill{i}lvl", "")
        exp = fields.get(f"skill{i}exp", "")
        boostable = fields.get(f"skill{i}boostable", "")
        yield level, name, exp, boostable


def _enumerate_pairs(prefix: str, fields: dict[str, str]) -> Iterator[tuple[str, str]]:
    """Yield (name, quantity) for each indexed `prefix` field (mat1 + mat1quantity, …).

    Materials and outputs share this shape — only the field prefix differs.
    """
    for i in _enumerate_index(prefix, fields):
        name = _clean(fields[f"{prefix}{i}"])
        qty = fields.get(f"{prefix}{i}quantity", "")
        yield name, qty


TOOL = register(
    ToolSpec(
        name="get_item_recipe",
        description="Get the crafting recipe for a RuneScape item — required skills, materials, tools, and output.",
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
        invoke=lambda args: get_item_recipe(args["item_name"], args.get("game", "rs3")),
    )
)
