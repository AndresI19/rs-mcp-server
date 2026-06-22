"""Tests for the @instrument decorator's systemic error backstop.

instrument() is the single seam every tool passes through, so it is where the
recurring "unhandled upstream HTTP error crashes the tool" class is closed — once,
for all 14 tools — while genuine programming bugs still surface for fixing.
"""
import httpx
import pytest

from rs_mcp_server.logging import instrument


@pytest.mark.anyio
async def test_unhandled_request_error_returns_friendly_message():
    @instrument("get_demo_thing")
    async def tool(x):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "http://x"))

    result = await tool("hi")
    assert "get demo thing" in result
    assert "unavailable" in result


@pytest.mark.anyio
async def test_unhandled_status_error_returns_friendly_message():
    @instrument("get_demo_thing")
    async def tool():
        raise httpx.HTTPStatusError(
            "503", request=httpx.Request("GET", "http://x"), response=httpx.Response(503)
        )

    assert "unavailable" in await tool()


@pytest.mark.anyio
async def test_programming_bug_still_propagates():
    # A non-HTTP error is a real bug and must NOT be masked by the backstop.
    @instrument("get_demo_thing")
    async def tool():
        raise ValueError("real bug")

    with pytest.raises(ValueError):
        await tool()
