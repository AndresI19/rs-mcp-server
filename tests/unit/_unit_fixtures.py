"""Fixtures specific to unit tests (run in-process, no live server)."""
import pytest

from rs_mcp_server import cache


@pytest.fixture(autouse=True)
def reset_cache():
    cache._store.clear()
    yield
    cache._store.clear()
