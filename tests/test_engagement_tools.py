from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.engagement import register_engagement_tools


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
            "linkedin_mcp_server.tools.engagement.get_ready_extractor", ready
        )
        return ready

    return serve


async def test_react_to_post_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "reacted"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_engagement_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "react_to_post")

    result = await tool_fn(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/", "like", mock_context
    )

    assert result["status"] == "reacted"


async def test_react_to_post_button_missing(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_engagement_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "react_to_post")

    with pytest.raises(ToolError, match="reaction"):
        await tool_fn(
            "https://www.linkedin.com/feed/update/urn:li:activity:1/",
            "like",
            mock_context,
        )


async def test_comment_on_post_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "set", "text": "Nice post"},
            {"status": "posted"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_engagement_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "comment_on_post")

    result = await tool_fn(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        "Nice post",
        mock_context,
    )

    assert result["status"] == "commented"
    assert result["text"] == "Nice post"


async def test_comment_on_post_dry_run(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "set", "text": "Draft"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_engagement_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "comment_on_post")

    result = await tool_fn(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        "Draft",
        mock_context,
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert extractor.page.evaluate.await_count == 1


async def test_reply_to_comment_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "Thanks"},
            {"status": "posted"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_engagement_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "reply_to_comment")

    result = await tool_fn(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        0,
        "Thanks",
        mock_context,
    )

    assert result["status"] == "replied"


async def test_get_post_reactions(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "ok", "counts": "42 reactions", "top": ["Like", "Love"]},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_engagement_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "get_post_reactions")

    result = await tool_fn(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/", mock_context
    )

    assert result["counts"] == "42 reactions"
