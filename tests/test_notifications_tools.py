from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.notifications import register_notifications_tools


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
            "linkedin_mcp_server.tools.notifications.get_ready_extractor", ready
        )
        return ready

    return serve


async def test_get_notifications_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {
                "status": "ok",
                "notifications": [
                    {"text": "Alice accepted your invitation", "unread": True}
                ],
            }
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_notifications_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "get_notifications")

    result = await tool_fn(mock_context)

    assert result["status"] == "ok"
    assert result["notifications"][0]["unread"] is True


async def test_get_notifications_empty(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "ok", "notifications": []}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_notifications_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "get_notifications")

    result = await tool_fn(mock_context)

    assert result["notifications"] == []


async def test_mark_notifications_read(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "clicked"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_notifications_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "mark_notifications_read")

    result = await tool_fn(mock_context)

    assert result["status"] == "marked_read"


async def test_mark_notifications_read_no_control(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_notifications_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "mark_notifications_read")

    with pytest.raises(ToolError, match="mark"):
        await tool_fn(mock_context)
