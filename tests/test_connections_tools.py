from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.connections import register_connections_tools


async def get_tool_fn(
    mcp: FastMCP, name: str
) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    tool = await mcp.get_tool(name)
    if tool is None:
        raise ValueError(f"Tool '{name}' not found")
    return cast(FunctionTool, tool).fn


def _make_extractor(evaluate_results: list[dict[str, Any]]) -> MagicMock:
    extractor = MagicMock()
    extractor.extract_page = AsyncMock(return_value=MagicMock())
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=evaluate_results)
    extractor.page = page
    return extractor


@pytest.fixture
def serve_extractor(monkeypatch: pytest.MonkeyPatch):
    def serve(extractor: Any) -> AsyncMock:
        ready = AsyncMock(return_value=extractor)
        monkeypatch.setattr(
            "linkedin_mcp_server.tools.connections.get_ready_extractor", ready
        )
        return ready

    return serve


async def test_list_pending_invitations(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {
                "status": "ok",
                "invitations": [
                    {"name": "Alice", "headline": "Engineer", "time": "2d"}
                ],
            }
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_connections_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "list_pending_invitations")

    result = await tool_fn(mock_context)

    assert result["status"] == "ok"
    assert result["invitations"][0]["name"] == "Alice"


async def test_accept_invitation_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "clicked", "name": "Alice"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_connections_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "accept_invitation")

    result = await tool_fn("Alice", mock_context)

    assert result["status"] == "accepted"


async def test_accept_invitation_not_found(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_connections_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "accept_invitation")

    with pytest.raises(ToolError, match="invitation"):
        await tool_fn("Ghost", mock_context)


async def test_decline_invitation_dry_run(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "clicked", "name": "Bob"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_connections_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "decline_invitation")

    result = await tool_fn("Bob", mock_context, dry_run=True)

    assert result["status"] == "dry_run"
    assert extractor.page.evaluate.await_count == 1


async def test_withdraw_connection_request(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "sent_tab_opened"},
            {"status": "withdraw_clicked", "name": "Alice"},
            {"status": "confirmed"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_connections_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "withdraw_connection_request")

    result = await tool_fn("Alice", mock_context)

    assert result["status"] == "withdrawn"
