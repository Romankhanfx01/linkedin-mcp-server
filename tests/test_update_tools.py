from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.update import register_update_tools


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
            "linkedin_mcp_server.tools.update.get_ready_extractor", ready
        )
        return ready

    return serve


async def test_update_headline_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "New Headline"},
            {"status": "saved"},
            {"status": "ok", "text": "New Headline"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_headline")

    result = await tool_fn(
        "https://www.linkedin.com/in/me/", "New Headline", mock_context
    )

    assert result["url"] == "https://www.linkedin.com/in/me/"
    assert result["field"] == "headline"
    assert result["value"] == "New Headline"
    assert result["confirmed_text"] == "New Headline"
    extractor.extract_page.assert_awaited_once_with(
        "https://www.linkedin.com/in/me/", "main_profile"
    )


async def test_update_about_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "New About"},
            {"status": "saved"},
            {"status": "ok", "text": "New About"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_about")

    result = await tool_fn("https://www.linkedin.com/in/me/", "New About", mock_context)

    assert result["field"] == "about"
    assert result["value"] == "New About"
    assert result["confirmed_text"] == "New About"


async def test_update_headline_no_edit_control(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_headline")

    with pytest.raises(ToolError, match="No editable headline control"):
        await tool_fn("https://www.linkedin.com/in/me/", "New Headline", mock_context)


async def test_update_about_no_edit_control(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_about")

    with pytest.raises(ToolError, match="No editable about control"):
        await tool_fn("https://www.linkedin.com/in/me/", "New About", mock_context)


async def test_update_headline_editor_not_writable(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "opened"}, {"status": "no_editor"}, {"status": "no_editor"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_headline")

    with pytest.raises(ToolError, match="Could not write the new headline"):
        await tool_fn("https://www.linkedin.com/in/me/", "New Headline", mock_context)


async def test_update_about_save_control_missing(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "New About"},
            {"status": "save_not_found"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_about")

    with pytest.raises(ToolError, match="did not expose a save control"):
        await tool_fn("https://www.linkedin.com/in/me/", "New About", mock_context)


async def test_update_about_not_confirmed(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "New About"},
            {"status": "saved"},
            {"status": "ok", "text": "Old About"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_about")

    with pytest.raises(ToolError, match="could not be confirmed"):
        await tool_fn("https://www.linkedin.com/in/me/", "New About", mock_context)


async def test_get_ready_extractor_called_with_tool_name(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened"},
            {"status": "set", "text": "x"},
            {"status": "saved"},
            {"status": "ok", "text": "x"},
        ]
    )
    ready = serve_extractor(extractor)

    mcp = FastMCP("test")
    register_update_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_headline")

    await tool_fn("https://www.linkedin.com/in/me/", "x", mock_context)

    ready.assert_awaited_once_with(mock_context, tool_name="update_headline")
