from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from linkedin_mcp_server.tools.job_actions import register_job_actions_tools


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
            "linkedin_mcp_server.tools.job_actions.get_ready_extractor", ready
        )
        return ready

    return serve


def _job_url() -> str:
    return "https://www.linkedin.com/jobs/view/1234567890/"


async def test_save_job_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "saved", "pressed": True},
            {"status": "ok", "pressed": True},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_job_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "save_job")

    result = await tool_fn(_job_url(), mock_context)

    assert result["status"] == "saved"


async def test_save_job_control_missing(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_job_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "save_job")

    with pytest.raises(ToolError, match="save"):
        await tool_fn(_job_url(), mock_context)


async def test_unsave_job_success(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "unsaved", "pressed": False},
            {"status": "ok", "pressed": False},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_job_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "unsave_job")

    result = await tool_fn(_job_url(), mock_context)

    assert result["status"] == "unsaved"


async def test_apply_to_job_easy_apply(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "opened", "dialog": True},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_job_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "apply_to_job")

    result = await tool_fn(_job_url(), mock_context)

    assert result["status"] == "opened"


async def test_apply_to_job_external(mock_context, serve_extractor):
    extractor = _make_extractor(
        [
            {"status": "external", "apply_url": "https://example.com/apply"},
        ]
    )
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_job_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "apply_to_job")

    result = await tool_fn(_job_url(), mock_context)

    assert result["status"] == "external"
    assert result["apply_url"] == "https://example.com/apply"


async def test_apply_to_job_unavailable(mock_context, serve_extractor):
    extractor = _make_extractor([{"status": "not_found"}])
    serve_extractor(extractor)

    mcp = FastMCP("test")
    register_job_actions_tools(mcp)
    tool_fn = await get_tool_fn(mcp, "apply_to_job")

    with pytest.raises(ToolError, match="apply"):
        await tool_fn(_job_url(), mock_context)
