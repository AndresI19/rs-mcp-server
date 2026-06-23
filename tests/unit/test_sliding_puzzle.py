"""Unit tests for the solve_sliding_puzzle tool (puzzle-box / sliding-tile solver).

The vision step (screenshot -> grid) is Claude's job and is not tested here; these tests
exercise only the deterministic solver — see the image-puzzle vision-boundary memo. The
solver's contract is reliability, so the round-trip tests assert that replaying the returned
moves (and the compressed clicks) actually reaches the solved board, across every board size
and every corner the gap can call home."""
import random

import pytest

from rs_mcp_server.tools.sliding_puzzle import (
    _MOVES,
    _OPPOSITE,
    _is_solvable,
    _parse,
    _solve,
    _to_clicks,
    solve_sliding_puzzle,
)


def _scramble(n, blank, steps, seed):
    """A guaranteed-solvable board: random-walk the gap from the solved state."""
    rng = random.Random(seed)
    board = list(range(n * n))
    gap = blank
    last = None
    for _ in range(steps):
        gr, gc = divmod(gap, n)
        opts = [(m, d) for m, d in _MOVES.items()
                if m != _OPPOSITE.get(last) and 0 <= gr + d[0] < n and 0 <= gc + d[1] < n]
        m, (dr, dc) = rng.choice(opts)
        swap = (gr + dr) * n + (gc + dc)
        board[gap], board[swap] = board[swap], board[gap]
        gap, last = swap, m
    return tuple(board)


def _replay_moves(board, moves, n, blank):
    state = list(board)
    gap = state.index(blank)
    for m in moves:
        dr, dc = _MOVES[m]
        gr, gc = divmod(gap, n)
        swap = (gr + dr) * n + (gc + dc)
        state[gap], state[swap] = state[swap], state[gap]
        gap = swap
    return tuple(state)


def _replay_clicks(board, clicks, n, blank):
    """Execute clicks as RuneScape slides: the clicked tile and everything between it and the
    gap shift one step toward the gap."""
    state = list(board)
    for r, c in clicks:  # clicks are 1-based
        r, c = r - 1, c - 1
        gap = state.index(blank)
        gr, gc = divmod(gap, n)
        if gr == r:
            step = 1 if c < gc else -1
            for cc in range(gc, c, -step):
                state[gr * n + cc] = state[gr * n + cc - step]
        elif gc == c:
            step = 1 if r < gr else -1
            for rr in range(gr, r, -step):
                state[rr * n + gc] = state[(rr - step) * n + gc]
        else:
            raise AssertionError("click not aligned with the gap")
        state[r * n + c] = blank
    return tuple(state)


def _to_grid(state, blank):
    return [None if v == blank else v for v in state]


class TestParse:
    def test_derives_blank_home_from_missing_index(self):
        n, state, blank = _parse([0, 1, 2, 3, None, 5, 6, 7, 8])
        assert n == 3
        assert blank == 4              # the index absent from the tiles is the gap's home
        assert state[4] == 4           # null is filled with the gap's home value

    def test_non_square_length_rejected(self):
        with pytest.raises(ValueError, match="square board"):
            _parse([0, 1, 2, 3, None])

    def test_requires_exactly_one_gap(self):
        with pytest.raises(ValueError, match="one cell must be the gap"):
            _parse([0, 1, 2, None, None, 5, 6, 7, 8])

    def test_duplicate_goal_positions_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            _parse([0, 1, 2, 3, 3, 5, 6, 7, None])

    def test_out_of_range_value_rejected(self):
        with pytest.raises(ValueError, match="0\\.\\."):
            _parse([0, 1, 2, 3, 99, 5, 6, 7, None])


class TestSolvability:
    def test_scrambled_board_is_solvable(self):
        state = _scramble(4, 15, 200, seed=1)
        assert _is_solvable(state, 4, 15)

    def test_single_swap_is_unsolvable(self):
        # The solved board with two non-gap tiles swapped has the wrong parity.
        state = list(range(9))
        state[0], state[1] = state[1], state[0]
        assert not _is_solvable(tuple(state), 3, 8)


class TestSolver:
    def test_already_solved_returns_no_moves(self):
        assert _solve(tuple(range(9)), 3, 8) == []

    @pytest.mark.parametrize("n", [3, 4, 5])
    def test_moves_solve_every_corner(self, n):
        for blank in (0, n - 1, (n - 1) * n, n * n - 1):
            for seed in range(8):
                state = _scramble(n, blank, 250, seed)
                moves = _solve(state, n, blank)
                assert _replay_moves(state, moves, n, blank) == tuple(range(n * n))

    def test_solves_full_size_24_puzzle(self):
        # RuneScape puzzle boxes are 5x5; this is the realistic worst case.
        state = _scramble(5, 24, 500, seed=99)
        moves = _solve(state, 5, 24)
        assert _replay_moves(state, moves, 5, 24) == tuple(range(25))

    def test_non_corner_gap_is_declined(self):
        # gap home at the centre of a 3x3 (cell 4) — not a corner.
        assert _solve(_scramble(3, 4, 50, seed=2), 3, 4) is None


class TestClicks:
    def test_same_direction_run_compresses_to_one_click(self):
        # gap starts at cell 0 (top-left of a 3x3); two "right" moves = one click two cells over.
        clicks = _to_clicks(["right", "right"], gap=0, n=3)
        assert clicks == [(1, 3)]

    def test_clicks_replay_to_solved_board(self):
        for n in (3, 4, 5):
            for blank in (0, n - 1, (n - 1) * n, n * n - 1):
                state = _scramble(n, blank, 200, seed=blank + 4)
                moves = _solve(state, n, blank)
                clicks = _to_clicks(moves, state.index(blank), n)
                assert _replay_clicks(state, clicks, n, blank) == tuple(range(n * n))


class TestEntryPoint:
    @pytest.mark.anyio
    async def test_no_args_returns_reading_guide(self):
        out = await solve_sliding_puzzle()
        assert "Reading a puzzle box" in out
        assert "null" in out and "perfect square" in out


class TestToolResponse:
    @pytest.mark.anyio
    async def test_solution_lists_clicks(self):
        grid = _to_grid(_scramble(3, 8, 30, seed=7), blank=8)
        out = await solve_sliding_puzzle(grid)
        assert "Puzzle box solution" in out
        assert "Click row" in out

    @pytest.mark.anyio
    async def test_already_solved_message(self):
        out = await solve_sliding_puzzle([0, 1, 2, 3, 4, 5, 6, 7, None])
        assert "already solved" in out

    @pytest.mark.anyio
    async def test_unsolvable_is_reported(self):
        # solved board with two tiles swapped -> unreachable parity.
        grid = [1, 0, 2, 3, 4, 5, 6, 7, None]
        out = await solve_sliding_puzzle(grid)
        assert "unsolvable as read" in out

    @pytest.mark.anyio
    async def test_bad_grid_returns_validation_message(self):
        out = await solve_sliding_puzzle([0, 1, 2, None])
        assert "square board" in out

    @pytest.mark.anyio
    async def test_non_corner_gap_message(self):
        grid = _to_grid(_scramble(3, 4, 40, seed=3), blank=4)  # centre gap
        out = await solve_sliding_puzzle(grid)
        assert "corner" in out
