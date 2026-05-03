"""Shared test fixtures for rs-mcp-server."""
import pytest

from rs_mcp_server import cache


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_cache():
    cache._store.clear()
    yield
    cache._store.clear()
