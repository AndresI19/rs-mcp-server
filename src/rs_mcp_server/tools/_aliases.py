"""Common in-game ↔ wiki name aliases, applied when direct title lookups miss."""
import re

# (in-game keyword, wiki keyword) — case-insensitive whole-word substitution.
# Conservative initial set; extend per real-world failures.
_ALIASES: tuple[tuple[str, str], ...] = (
    ("gauntlets", "melee gloves"),
    ("helm", "helmet"),
)


def expand_aliases(name: str) -> list[str]:
    """Return [original] plus any alias-substituted alternates, deduped, original first."""
    forms = [name]
    for source, target in _ALIASES:
        pattern = rf"\b{re.escape(source)}\b"
        if re.search(pattern, name, re.IGNORECASE):
            forms.append(re.sub(pattern, target, name, flags=re.IGNORECASE))
    return list(dict.fromkeys(forms))
