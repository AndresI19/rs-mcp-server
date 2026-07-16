"""Importing this package registers every tool into REGISTRY (via each module's `register()` call).

The import ORDER below defines the tool-list order (`search_wiki` first, …), which mirrors the tools'
original declaration order in server.py. server.py reads REGISTRY to list and dispatch tools.
"""

# ruff: noqa: I001  — the tool imports are ordered semantically (the tool-list order), NOT alphabetically,
# so this file opts out of import sorting. Each import runs the module's register() side effect.
from ._registry import REGISTRY

from . import wiki  # noqa: F401
from . import prices  # noqa: F401
from . import hiscores  # noqa: F401
from . import quests  # noqa: F401
from . import recipes  # noqa: F401
from . import equipment  # noqa: F401
from . import monsters  # noqa: F401
from . import drops  # noqa: F401
from . import achievements  # noqa: F401
from . import player_progress  # noqa: F401
from . import moneymakers  # noqa: F401
from . import alchables  # noqa: F401
from . import settings  # noqa: F401
from . import clues  # noqa: F401
from . import celtic_knot  # noqa: F401
from . import sliding_puzzle  # noqa: F401

__all__ = ["REGISTRY"]
