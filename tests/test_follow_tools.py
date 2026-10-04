from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.follow import register_follow_tools


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
            "linkedin_mcp_server.tools.follow.get_ready_extractor", ready
        )
        return ready

    return serve


async def test_follow_person_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "followed", "following": True},
            {"status": "ok", "following": True},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_follow_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "follow_person")

    result = await tool_fn("alice", mock_context)

    assert result["status"] == "followed"


async def test_follow_person_already_following(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "already_following"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_follow_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "follow_person")

    result = await tool_fn("alice", mock_context)

    assert result["status"] == "already_following"


async def test_unfollow_person_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "unfollowed", "following": False},
            {"status": "ok", "following": False},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_follow_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "unfollow_person")

    result = await tool_fn("alice", mock_context)

    assert result["status"] == "unfollowed"


async def test_follow_company_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "followed", "following": True},
            {"status": "ok", "following": True},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_follow_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "follow_company")

    result = await tool_fn("acme-corp", mock_context)

    assert result["status"] == "followed"


async def test_unfollow_company_control_missing(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_follow_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "unfollow_company")

    with pytest.raises(ToolError, match="follow"):
        await tool_fn("acme-corp", mock_context)
