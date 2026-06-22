"""Unit tests for the solve_celtic_knot solver (issue #98)."""
import pytest

from rs_mcp_server.tools.celtic_knot import (
    _consistent,
    _describe_rotation,
    _find_solutions,
    solve_celtic_knot,
)


def _rot_fwd(ring: list, k: int) -> list:
    n = len(ring)
    return [ring[(p - k) % n] for p in range(n)]


# A solved knot: rings share the matching rune at each intersection.
_SOLVED = [[1, 2, 3, 4], [1, 5, 6, 7], [8, 5, 3, 9]]
_INTERSECTIONS = [[0, 0, 1, 0], [1, 1, 2, 1], [0, 2, 2, 2]]  # 1==1, 5==5, 3==3


class TestSolver:
    def test_round_trip_recovers_a_valid_solution(self):
        current = [_rot_fwd(_SOLVED[r], k) for r, k in zip(range(3), [1, 2, 3])]
        sols = _find_solutions(current, _INTERSECTIONS)
        assert sols
        assert all(_consistent(current, _INTERSECTIONS, s) for s in sols)

    def test_hidden_rune_is_a_wildcard(self):
        rings = [[1, 2], [1, 2]]
        ix = [[0, 0, 1, 0]]
        assert _find_solutions(rings, ix)
        rings[0][0] = None  # occluded — must not rule out the real answer
        assert _find_solutions(rings, ix)


class TestDescribeRotation:
    def test_prefers_shorter_direction(self):
        assert "backward" in _describe_rotation(3, 4)   # 3 forward == 1 backward
        assert "forward" in _describe_rotation(1, 4)
        assert _describe_rotation(0, 4) == "leave as-is"


class TestToolResponse:
    @pytest.mark.anyio
    async def test_solution_names_every_ring(self):
        current = [_rot_fwd(_SOLVED[r], k) for r, k in zip(range(3), [1, 2, 3])]
        out = await solve_celtic_knot(current, _INTERSECTIONS)
        assert all(f"Ring {r}" in out for r in range(3))
        assert "solution" in out.lower()

    @pytest.mark.anyio
    async def test_no_solution_message(self):
        out = await solve_celtic_knot([[1, 1], [2, 2]], [[0, 0, 1, 0]])
        assert "No rotation makes every intersection match" in out

    @pytest.mark.anyio
    async def test_under_determined_message(self):
        # All-identical runes → every rotation matches → too many candidates.
        out = await solve_celtic_knot([[1, 1, 1, 1], [1, 1, 1, 1]], [[0, 0, 1, 0]])
        assert "Under-determined" in out

    @pytest.mark.anyio
    async def test_validation_rejects_bad_ring_index(self):
        out = await solve_celtic_knot([[1, 2]], [[0, 0, 5, 0]])
        assert "ring index" in out

    @pytest.mark.anyio
    async def test_empty_ring_within_list_rejected(self):
        out = await solve_celtic_knot([[1, 2], []], [[0, 0, 1, 0]])
        assert "non-empty" in out


class TestEntryPoint:
    @pytest.mark.anyio
    async def test_no_args_returns_tokenize_guide(self):
        out = await solve_celtic_knot()
        assert "Reading a Celtic knot" in out
        assert "intersections" in out and "null" in out


class TestRealisticScale:
    def test_solves_full_size_knot(self):
        # 3 rings of 24 runes with 6 crossings — in-game dimensions, not the toy length-4.
        n = 24
        rings = [[f"r{r}_{i}" for i in range(n)] for r in range(3)]   # all distinct base runes
        intersections = [
            [0, 2, 1, 5], [0, 9, 2, 3], [0, 16, 1, 20],
            [1, 1, 2, 18], [1, 12, 2, 7], [0, 22, 2, 14],
        ]
        for j, (ra, pa, rb, pb) in enumerate(intersections):  # plant a shared token per crossing
            rings[ra][pa] = rings[rb][pb] = f"X{j}"
        offsets = [5, 11, 19]
        current = [[rings[r][(p - offsets[r]) % n] for p in range(n)] for r in range(3)]
        sols = _find_solutions(current, intersections)
        assert sols, "full-size knot should be solvable"
        assert all(_consistent(current, intersections, s) for s in sols)
