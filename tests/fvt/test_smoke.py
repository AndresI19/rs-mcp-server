"""Function-verification smoke tests — exercises every MCP tool against a live endpoint.

Replaces the manual scripts/smoke_test_tools.py runner. Requires a live MCP endpoint — by default
the container on localhost:8000, or the open-vMCP gateway when the FVT_* variables point there (see
_fvt_fixtures). If nothing answers, the entire suite skips with a clear message.
"""
import pytest

from tests.fvt._fvt_fixtures import CASE_PARAMS, EXPECTED_TOOLS

pytestmark = pytest.mark.fvt


@pytest.mark.anyio
async def test_server_registers_expected_tools(mcp_session):
    tools = {t.name for t in (await mcp_session.list_tools()).tools}
    missing = EXPECTED_TOOLS - tools
    assert not missing, f"server missing expected tools: {sorted(missing)}"


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "args", "expected_substrings"), CASE_PARAMS)
async def test_tool_invocation(mcp_session, tool, args, expected_substrings):
    result = await mcp_session.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
    assert not result.isError, f"{tool}({args}) returned isError; text={text[:300]!r}"
    missing = [s for s in expected_substrings if s not in text]
    assert not missing, f"{tool}({args}) missing {missing} in:\n{text[:500]}"
