"""solve_celtic_knot tool — deterministic solver for RS3 Celtic knot clue puzzles.

The vision step (reading a screenshot into per-ring rune tokens plus the intersection
constraints) is done by the multimodal agent. This tool is the pure search: given the
rings as token arrays and the intersections as (ring, slot) equality pairs, it finds the
ring rotations that make every intersection match.

Key ideas:
- Runes are *tokens*, not identities — the agent only needs equal runes to share a token
  (consistent across all rings); it never needs to know what a rune depicts.
- The puzzle's INVERT PATHS button reveals the runes hidden under crossings, so the agent
  reads both views and supplies *complete* rings — and a complete reading has a single
  rotation solution. ``None`` (wildcard) is still accepted for a genuinely unreadable rune,
  but it is the fallback, not the norm.

A knot is 3-4 loops of up to ~30 runes with 2-6 intersections, so the rotation space
(product of ring lengths) is small enough to brute-force.
"""
import itertools

from rs_mcp_server.logging import instrument

# If more than this many rotation sets satisfy the visible runes, the screenshot didn't
# reveal enough runes to pin a single answer — ask for more rather than guessing.
_MAX_CANDIDATES = 8

# Returned when the tool is called with no rings: it teaches the agent how to turn a
# screenshot into the (rings, intersections) the solver needs, then call back to solve.
_TOKENIZE_GUIDE = """**Reading a Celtic knot for solve_celtic_knot**

A Celtic knot is 3-4 coloured loops, each a cycle of up to ~30 runestones. You rotate the
loops with their arrows until the two runes meeting at every crossing match (each junction
turns green), then click UNLOCK. Read the screenshot into two arguments and call back.

**Reveal the hidden runes first — don't guess them.** At each crossing one path passes over
the other and hides the under-path's rune. The puzzle has an **INVERT PATHS** button (lower
-left) that flips which path is on top, exposing the runes that were hidden. Read the knot in
BOTH views — normal and inverted — so you can see *every* runestone. This is the whole trick:
with both views there is no missing information, so the solver returns one exact answer.

**1. `rings`** — one array per coloured loop. Walk each loop from a consistent start (e.g.
the top slot, clockwise) and encode each rune as a TOKEN: give every distinct rune a number
and reuse the SAME number for that rune everywhere it appears, **including across loops**.
You never need to know what a rune depicts — only "same rune → same token". Fill every slot
from your two-view reading; use `null` only for a rune you genuinely cannot make out.

**2. `intersections`** — one entry per crossing as `[ring_a, slot_a, ring_b, slot_b]`,
meaning the rune at slot_a of ring_a must equal the rune at slot_b of ring_b for that
junction to turn green. Slot indices are 0-based positions in the step-1 arrays.

Then call `solve_celtic_knot(rings, intersections)` for the per-loop rotation. A complete
reading resolves to a single solution; if you leave runes as `null` the answer may be
ambiguous, and the tool will tell you to flip the paths and reveal more."""


def _runes_match(a, b) -> bool:
    """Two runes match if equal, or if either is hidden (None = wildcard)."""
    return a is None or b is None or a == b


def _consistent(rings: list[list], intersections: list[list], ks: tuple[int, ...]) -> bool:
    """Do all intersections match when ring r is rotated forward by ks[r]?

    Rotating a ring forward by k moves the rune at position p to (p + k); equivalently,
    after rotation position p shows ring[(p - k) % n].
    """
    for ra, pa, rb, pb in intersections:
        na, nb = len(rings[ra]), len(rings[rb])
        if not _runes_match(rings[ra][(pa - ks[ra]) % na], rings[rb][(pb - ks[rb]) % nb]):
            return False
    return True


def _find_solutions(rings: list[list], intersections: list[list]) -> list[tuple[int, ...]]:
    """All rotation tuples (one offset per ring) that satisfy every intersection,
    collected up to _MAX_CANDIDATES + 1 so the caller can detect under-determination."""
    solutions: list[tuple[int, ...]] = []
    for ks in itertools.product(*(range(len(r)) for r in rings)):
        if _consistent(rings, intersections, ks):
            solutions.append(ks)
            if len(solutions) > _MAX_CANDIDATES:
                break
    return solutions


def _validate(rings: list[list], intersections: list[list]) -> str | None:
    if not rings or any(len(r) == 0 for r in rings):
        return "Provide each ring as a non-empty array of rune tokens (use null for hidden runes)."
    if not intersections:
        return "Provide the intersections as [ring_a, slot_a, ring_b, slot_b] equality pairs."
    nr = len(rings)
    for ix in intersections:
        if len(ix) != 4:
            return f"Each intersection must be [ring_a, slot_a, ring_b, slot_b]; got {ix}."
        ra, pa, rb, pb = ix
        if not (0 <= ra < nr and 0 <= rb < nr):
            return f"Intersection {ix} references a ring index outside 0..{nr - 1}."
        if not (0 <= pa < len(rings[ra]) and 0 <= pb < len(rings[rb])):
            return f"Intersection {ix} references a slot outside its ring's length."
    return None


def _describe_rotation(k: int, n: int) -> str:
    """Net rotation k as the fewer-clicks direction."""
    if k == 0:
        return "leave as-is"
    forward, backward = k, n - k
    if forward <= backward:
        return f"rotate {forward} step{'s' if forward != 1 else ''} forward"
    return f"rotate {backward} step{'s' if backward != 1 else ''} backward"


def _clicks(ks: tuple[int, ...], lengths: list[int]) -> int:
    return sum(min(k, n - k) for k, n in zip(ks, lengths))


@instrument("solve_celtic_knot")
async def solve_celtic_knot(
    rings: list[list] | None = None, intersections: list[list] | None = None
) -> str:
    # Phase 1 — no data yet: hand the agent the protocol for reading the screenshot.
    if not rings:
        return _TOKENIZE_GUIDE

    # Phase 2 — solve the tokenised knot.
    error = _validate(rings, intersections or [])
    if error:
        return error

    lengths = [len(r) for r in rings]
    solutions = _find_solutions(rings, intersections)

    if not solutions:
        return ("These runes have no consistent rotation — the knot is **unsolvable as read**. A real "
                "Celtic knot always has a solution, so this almost always means a rune was misread or "
                "an intersection was mis-mapped; double-check those. If the reading is definitely "
                "correct, the puzzle is genuinely unsolvable.")

    if len(solutions) > _MAX_CANDIDATES:
        return ("**Too many rotations fit to pin one answer.** More than "
                f"{_MAX_CANDIDATES} rotation sets satisfy the runes as read — usually because runes were "
                "left hidden (`null`). Click the puzzle's **INVERT PATHS** button to expose the runes "
                "tucked under the crossings, re-read so every slot is filled, and call again; a complete "
                "reading resolves to a single solution.")

    solutions.sort(key=lambda ks: _clicks(ks, lengths))
    best = solutions[0]
    lines = ["**Celtic knot solution** — rotate each loop with its arrows:", ""]
    for r, k in enumerate(best):
        lines.append(f"- Ring {r}: {_describe_rotation(k, lengths[r])}")
    if len(solutions) == 1:
        lines += ["", "Every junction will turn green — then click UNLOCK."]
    else:
        lines += [
            "",
            f"{len(solutions)} rotation sets fit the runes read (some were `null`); this is the fewest "
            "clicks. If a junction stays red, a hidden rune differed — use INVERT PATHS to read the "
            "under-runes and retry.",
        ]
    return "\n".join(lines)
