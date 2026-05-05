"""Fixtures shared across both unit and FVT tests."""
import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
