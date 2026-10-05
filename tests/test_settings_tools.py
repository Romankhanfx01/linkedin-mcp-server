from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.settings import register_settings_tools


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
            "linkedin_mcp_server.tools.settings.get_ready_extractor", ready
        )
        return ready

    return serve


async def test_list_settings_sections(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {
                "status": "ok",
                "sections": [
                    {"name": "Account preferences", "url": "/settings/account/"}
                ],
            }
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_settings_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "list_settings_sections")

    result = await tool_fn(mock_context)

    assert result["status"] == "ok"
    assert result["sections"][0]["name"] == "Account preferences"


async def test_get_setting(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {
                "status": "ok",
                "settings": [{"name": "Profile visibility", "value": "Anyone"}],
            }
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_settings_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "get_setting")

    result = await tool_fn("/settings/visibility/", mock_context)

    assert result["settings"][0]["value"] == "Anyone"


async def test_update_setting_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "located", "name": "Profile visibility"},
            {"status": "updated", "name": "Profile visibility"},
            {"status": "ok"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_settings_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_setting")

    result = await tool_fn(
        "/settings/visibility/", "Profile visibility", "Anyone", mock_context
    )

    assert result["status"] == "updated"


async def test_update_setting_not_found(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_settings_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_setting")

    with pytest.raises(ToolError, match="setting"):
        await tool_fn("/settings/visibility/", "Ghost", "x", mock_context)


async def test_update_setting_dry_run(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "located", "name": "Profile visibility"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_settings_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "update_setting")

    result = await tool_fn(
        "/settings/visibility/",
        "Profile visibility",
        "Anyone",
        mock_context,
        dry_run=True,
    )

    assert result["status"] == "dry_run"
