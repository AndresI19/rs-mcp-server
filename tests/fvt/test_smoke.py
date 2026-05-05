"""Function-verification smoke tests — exercises every MCP tool over SSE.

Replaces the manual scripts/smoke_test_tools.py runner. Requires a running rs-mcp-server
on localhost:8000; if absent, the entire suite skips with a clear message.
"""
import pytest

from tests.fvt._fvt_fixtures import CASE_IDS, CASES, EXPECTED_TOOLS

pytestmark = pytest.mark.fvt


@pytest.mark.anyio
async def test_server_registers_expected_tools(mcp_session):
    tools = {t.name for t in (await mcp_session.list_tools()).tools}
    missing = EXPECTED_TOOLS - tools
    assert not missing, f"server missing expected tools: {sorted(missing)}"


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "args", "expected_substrings"), CASES, ids=CASE_IDS)
async def test_tool_invocation(mcp_session, tool, args, expected_substrings):
    result = await mcp_session.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
    assert not result.isError, f"{tool}({args}) returned isError; text={text[:300]!r}"
    missing = [s for s in expected_substrings if s not in text]
    assert not missing, f"{tool}({args}) missing {missing} in:\n{text[:500]}"
