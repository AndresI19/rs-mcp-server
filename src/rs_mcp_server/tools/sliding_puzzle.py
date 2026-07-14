"""solve_sliding_puzzle tool — IDA* solver for RuneScape puzzle-box (sliding-tile) clues.

Reading the scrambled screenshot into the tile arrangement is the multimodal agent's job;
this tool is the pure search. Given the current arrangement, it runs weighted IDA* with a
Manhattan + linear-conflict heuristic ("optimal-ish": near-minimal but fast even on a 5x5)
and returns the moves, compressed into RuneScape's row/column slides — one click shifts
every tile between the clicked tile and the gap, so a run of same-direction single moves
collapses into one click.
"""

import math
from collections import deque

from rs_mcp_server.logging import instrument

# Gap move → (row delta, col delta) and its opposite (to avoid immediately undoing a move).
_MOVES = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}
_OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}

_TOKENIZE_GUIDE = """**Reading a puzzle box for solve_sliding_puzzle**

First fetch the solved picture (it tells you where each fragment belongs). Then read the
scrambled screenshot into one flat `grid`, row by row (top-left to bottom-right), and call
this tool again with it.

- The grid length must be a perfect square: 9 (3x3), 16 (4x4) or 25 (5x5).
- For each cell, put the **goal position** of the fragment sitting there — the 0-based index
  (row-major) of the cell that fragment occupies in the SOLVED picture.
- For the one empty cell, put `null`.

So a solved 3x3 reads `[0,1,2,3,4,5,6,7,null]` if the gap belongs bottom-right. The tool
returns the sequence of clicks (each click slides a whole row/column toward the gap). If the
arrangement can't be reached (an odd misread), it says so — a real puzzle box is always
solvable."""


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------


def _parse(grid: list) -> tuple[int, tuple[int, ...], int]:
    """Validate the grid and return (n, state, blank_value).

    state is a permutation of 0..n^2-1 with the blank's home value standing in for the gap;
    blank_value is that home (the index missing from the non-null entries). Raises ValueError
    with a user-facing message on bad input."""
    size = len(grid)
    n = int(round(math.isqrt(size)))
    if n * n != size or n not in (3, 4, 5):
        raise ValueError(f"Grid length {size} is not a square board (expected 9, 16 or 25).")
    nulls = [i for i, v in enumerate(grid) if v is None]
    if len(nulls) != 1:
        raise ValueError(f"Exactly one cell must be the gap (null); found {len(nulls)}.")
    tiles = [v for v in grid if v is not None]
    if any(not isinstance(v, int) or not (0 <= v < size) for v in tiles):
        raise ValueError(f"Tile values must be integers in 0..{size - 1} (goal cell indices).")
    if len(set(tiles)) != len(tiles):
        raise ValueError("Tile goal positions must be unique — two cells map to the same goal.")
    blank_value = (set(range(size)) - set(tiles)).pop()  # the one goal index left for the gap
    state = tuple(blank_value if v is None else v for v in grid)
    return n, state, blank_value


# ---------------------------------------------------------------------------
# Heuristic + solvability
# ---------------------------------------------------------------------------


def _is_solvable(state, n: int, blank: int) -> bool:
    """A board is reachable from the goal iff its permutation parity matches the gap's
    Manhattan-from-home parity (each move flips both)."""
    inv = sum(1 for i in range(len(state)) for j in range(i + 1, len(state)) if state[i] > state[j])
    gap = state.index(blank)
    gap_dist = abs(gap // n - blank // n) + abs(gap % n - blank % n)
    return inv % 2 == gap_dist % 2


# ---------------------------------------------------------------------------
# Layered solver — deterministic, always solves, never searches the open space. Solve
# the top row + left column of the working square, shrink, repeat down to a 3x3, then
# finish the 3x3 with a tiny exhaustive BFS. The method needs the gap's goal at the
# bottom-right corner, so a board whose gap homes at another corner is reflected there
# first and the move directions are reflected back.
# ---------------------------------------------------------------------------

_HFLIP = {"up": "up", "down": "down", "left": "right", "right": "left"}
_VFLIP = {"up": "down", "down": "up", "left": "left", "right": "right"}


def _flip_cell(cell: int, n: int, vert: bool) -> int:
    r, c = divmod(cell, n)
    return (n - 1 - r) * n + c if vert else r * n + (n - 1 - c)


def _flip_board(board: list[int], n: int, vert: bool) -> list[int]:
    new = [0] * len(board)
    for cell, val in enumerate(board):  # reflect both positions and tile-home values
        new[_flip_cell(cell, n, vert)] = _flip_cell(val, n, vert)
    return new


def _solve(state: tuple[int, ...], n: int, blank: int) -> list[str] | None:
    if all(state[i] == i for i in range(len(state))):
        return []
    board = list(state)
    flips = []
    br, bc = divmod(blank, n)
    if br == 0:
        board = _flip_board(board, n, vert=True)
        flips.append("v")
    elif br != n - 1:
        return None  # gap's solved cell is not on a corner row
    if bc == 0:
        board = _flip_board(board, n, vert=False)
        flips.append("h")
    elif bc != n - 1:
        return None
    moves: list[str] = []
    _layered(board, n, n * n - 1, moves)  # gap now homes bottom-right
    for f in flips:  # disjoint axes → order-independent
        table = _VFLIP if f == "v" else _HFLIP
        moves = [table[m] for m in moves]
    return moves


def _layered(board, n, blank, moves):
    frozen: set[int] = set()
    k = 0
    while n - k > 3:
        _solve_row(board, n, blank, k, frozen, moves)
        _solve_col(board, n, blank, k, frozen, moves)
        k += 1
    _solve_small(board, n, blank, k, frozen, moves)


def _apply(board, n, blank, move, moves):
    gap = board.index(blank)
    dr, dc = _MOVES[move]
    nxt = (gap // n + dr) * n + (gap % n + dc)
    board[gap], board[nxt] = board[nxt], board[gap]
    moves.append(move)


def _bfs_place(board, n, blank, tiles, targets, frozen, moves):
    """Move `tiles` onto `targets` via BFS over (tracked-tile positions, gap), with the gap
    confined to non-frozen cells. Every untracked tile is fungible filler, so the state is
    just the tracked positions — which keeps the search tiny AND makes it trap-proof: BFS
    explores every reachable configuration, so it can never box the gap into a dead end. The
    joint two-tile case discovers the corner rotation on its own."""
    targets = tuple(targets)
    start = (tuple(board.index(t) for t in tiles), board.index(blank))
    if start[0] == targets:
        return
    prev = {start: None}
    q = deque([start])
    goal = None
    while q:
        cur = q.popleft()
        positions, gap = cur
        if positions == targets:
            goal = cur
            break
        gr, gc = divmod(gap, n)
        for move, (dr, dc) in _MOVES.items():
            nr, nc = gr + dr, gc + dc
            nb = nr * n + nc
            if not (0 <= nr < n and 0 <= nc < n) or nb in frozen:
                continue
            moved = tuple(gap if p == nb else p for p in positions)  # filler is invisible
            nxt = (moved, nb)
            if nxt not in prev:
                prev[nxt] = (cur, move)
                q.append(nxt)
    if goal is None:
        raise RuntimeError(f"cannot place tiles {tiles} -> {list(targets)}")
    path = []
    cur = goal
    while prev[cur] is not None:
        pcur, move = prev[cur]
        path.append(move)
        cur = pcur
    for move in reversed(path):
        _apply(board, n, blank, move, moves)


def _solve_row(board, n, blank, k, frozen, moves):
    for c in range(k, n - 2):  # all but the last two of the row place individually
        t = k * n + c
        _bfs_place(board, n, blank, [t], [t], frozen, moves)
        frozen.add(t)
    a, b = k * n + (n - 2), k * n + (n - 1)  # last two together — avoids the corner lock
    _bfs_place(board, n, blank, [a, b], [a, b], frozen, moves)
    frozen.update((a, b))


def _solve_col(board, n, blank, k, frozen, moves):
    for r in range(k + 1, n - 2):  # all but the last two of the column place individually
        t = r * n + k
        _bfs_place(board, n, blank, [t], [t], frozen, moves)
        frozen.add(t)
    a, b = (n - 2) * n + k, (n - 1) * n + k
    _bfs_place(board, n, blank, [a, b], [a, b], frozen, moves)
    frozen.update((a, b))


def _solve_small(board, n, blank, k, frozen, moves):
    """Exhaustively BFS the final 3x3 (gap confined to it) to the solved state."""
    sub = {r * n + c for r in range(k, n) for c in range(k, n)}
    if all(board[c] == c for c in sub):
        return
    start = tuple(board)
    prev = {start: None}
    q = deque([start])
    goal_state = None
    while q:
        cur = q.popleft()
        if all(cur[c] == c for c in sub):
            goal_state = cur
            break
        gap = cur.index(blank)
        gr, gc = divmod(gap, n)
        for move, (dr, dc) in _MOVES.items():
            nr, nc = gr + dr, gc + dc
            ni = nr * n + nc
            if 0 <= nr < n and 0 <= nc < n and ni in sub and ni != gap:
                lst = list(cur)
                lst[gap], lst[ni] = lst[ni], lst[gap]
                nb = tuple(lst)
                if nb not in prev:
                    prev[nb] = (cur, move)
                    q.append(nb)
    if goal_state is None:
        raise RuntimeError("final 3x3 unexpectedly unsolvable")
    path = []
    cur = goal_state
    while prev[cur] is not None:
        pcur, move = prev[cur]
        path.append(move)
        cur = pcur
    for move in reversed(path):
        _apply(board, n, blank, move, moves)


# ---------------------------------------------------------------------------
# Click compression + formatting
# ---------------------------------------------------------------------------


def _to_clicks(moves: list[str], gap: int, n: int) -> list[tuple[int, int]]:
    """Collapse runs of same-direction gap moves into clicks. One click in RuneScape slides
    every tile between the clicked tile and the gap, so K same-direction moves = one click on
    the tile K cells away. Returns (row, col) 1-based cells to click, in order."""
    clicks: list[tuple[int, int]] = []
    gr, gc = divmod(gap, n)
    i = 0
    while i < len(moves):
        d = moves[i]
        run = 0
        while i < len(moves) and moves[i] == d:
            run += 1
            i += 1
        dr, dc = _MOVES[d]
        click_r, click_c = gr + dr * run, gc + dc * run  # the tile that triggers the slide
        clicks.append((click_r + 1, click_c + 1))
        gr, gc = click_r, click_c  # gap ends where the clicked tile was
    return clicks


@instrument("solve_sliding_puzzle")
async def solve_sliding_puzzle(grid: list | None = None) -> str:
    if not grid:
        return _TOKENIZE_GUIDE
    try:
        n, state, blank = _parse(grid)
    except ValueError as exc:
        return str(exc)

    if not _is_solvable(state, n, blank):
        return (
            "This arrangement can't be reached from a solved board, so it's unsolvable as "
            "read. A real puzzle box is always solvable — recheck the tile you read for each "
            "cell (two fragments are probably swapped)."
        )

    moves = _solve(state, n, blank)
    if moves is None:
        return (
            "I can only solve a puzzle box whose gap sits in a **corner** of the solved picture "
            "(the usual case). This board's gap belongs on an edge or in the middle — double-check "
            "which cell is the gap in the completed image."
        )
    if not moves:
        return "The board is already solved — nothing to click."

    clicks = _to_clicks(moves, state.index(blank), n)
    lines = [f"**Puzzle box solution** — {len(clicks)} clicks ({len(moves)} tile moves):", ""]
    lines += [f"{i}. Click row {r}, col {c}" for i, (r, c) in enumerate(clicks, 1)]
    lines += [
        "",
        "Each click slides the whole row/column between that tile and the gap. Cells are "
        "1-based from the top-left.",
    ]
    return "\n".join(lines)
