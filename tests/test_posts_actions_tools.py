from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.posts_actions import register_posts_actions_tools


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
    page.set_input_files = AsyncMock()
    extractor.page = page
    return extractor


@pytest.fixture
def serve_extractor(monkeypatch: pytest.MonkeyPatch):
    def serve(extractor: Any) -> AsyncMock:
        ready = AsyncMock(return_value=extractor)
        monkeypatch.setattr(
            "linkedin_mcp_server.tools.posts_actions.get_ready_extractor", ready
        )
        return ready

    return serve


async def test_create_post_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "Hello world"},
            {"status": "posted"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_posts_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "create_post")

    result = await tool_fn("Hello world", mock_context)

    assert result["status"] == "posted"
    assert result["text"] == "Hello world"


async def test_create_post_dry_run_skips_submit(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "Draft"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_posts_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "create_post")

    result = await tool_fn("Draft", mock_context, dry_run=True)

    assert result["status"] == "dry_run"
    assert extractor.page.evaluate.await_count == 2


async def test_create_post_composer_missing(mock_context, serve_extractor):
    extractor = _make_extractor(
        [{"status": "opened"}, {"status": "no_editor"}, {"status": "no_editor"}]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_posts_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "create_post")

    with pytest.raises(ToolError, match="Could not write text"):
        await tool_fn("Hello", mock_context)


async def test_delete_post_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "delete_clicked"},
            {"status": "confirmed"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_posts_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "delete_post")

    result = await tool_fn(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/", mock_context
    )

    assert result["status"] == "deleted"


async def test_delete_post_dry_run(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "delete_clicked"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_posts_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "delete_post")

    result = await tool_fn(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        mock_context,
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert extractor.page.evaluate.await_count == 2


async def test_create_post_with_image_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "With image"},
            {"status": "posted"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_posts_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "create_post_with_image")

    result = await tool_fn("With image", "C:\\tmp\\pic.png", mock_context)

    assert result["status"] == "posted"
    extractor.page.set_input_files.assert_awaited_once()
