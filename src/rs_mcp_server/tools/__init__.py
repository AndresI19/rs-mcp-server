"""Importing this package registers every tool into REGISTRY (via each module's `register()` call).

The import ORDER below defines the tool-list order (`search_wiki` first, …), which mirrors the tools'
original declaration order in server.py. server.py reads REGISTRY to list and dispatch tools.

ruff's F401 ("unused import") and I001 ("unsorted imports") are disabled for this file in
pyproject.toml: these imports exist for their register() side effect and are deliberately kept in
tool-list order, not alphabetised.
"""

from ._registry import REGISTRY

from . import (
    wiki,
    prices,
    hiscores,
    quests,
    recipes,
    equipment,
    monsters,
    drops,
    achievements,
    player_progress,
    moneymakers,
    alchables,
    settings,
    clues,
    celtic_knot,
    sliding_puzzle,
)

__all__ = ["REGISTRY"]
