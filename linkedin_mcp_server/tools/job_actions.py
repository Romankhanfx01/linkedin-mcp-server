"""Job action tools: save, unsave, apply."""

import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error

logger = logging.getLogger(__name__)

_SAVE_TOGGLE_JS = """() => {
  const buttons = Array.from(document.querySelectorAll('button')).filter(
    (b) => b.offsetParent !== null,
  );
  const save = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.trim().startsWith('save') || label.includes('save job');
  });
  if (!save) return { status: 'not_found' };
  const pressed = save.getAttribute('aria-pressed') === 'true';
  save.click();
  return pressed
    ? { status: 'unsaved', pressed: false }
    : { status: 'saved', pressed: true };
}"""

_VERIFY_SAVE_JS = """() => {
  const buttons = Array.from(document.querySelectorAll('button')).filter(
    (b) => b.offsetParent !== null,
  );
  const save = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.trim().startsWith('save') || label.includes('save job');
  });
  if (!save) return { status: 'not_found' };
  return {
    status: 'ok',
    pressed: save.getAttribute('aria-pressed') === 'true',
  };
}"""

_APPLY_JS = """() => {
  const buttons = Array.from(document.querySelectorAll('button, a')).filter(
    (b) => b.offsetParent !== null,
  );
  const easy = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('easy apply');
  });
  if (easy) {
    easy.click();
    return { status: 'opened', dialog: true };
  }
  const external = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('apply');
  });
  if (external) {
    const href = external.getAttribute('href') || '';
    external.click();
    return { status: 'external', apply_url: href };
  }
  return { status: 'not_found' };
}"""


async def _save_toggle(
    ctx: Context, *, tool_name: str, job_url: str, expect_saved: bool
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(job_url, "job_details")
        page = extractor.page

        toggled = await page.evaluate(_SAVE_TOGGLE_JS)
        if not isinstance(toggled, dict) or toggled.get("status") not in (
            "saved",
            "unsaved",
        ):
            raise ToolError(
                "No save control found on this job page; the job may not be "
                "visible or the URL may be invalid."
            )

        got = toggled.get("status")
        if (got == "saved") != expect_saved:
            # Undo the accidental flip so we never change the saved state
            # silently. Revert by flipping back once.
            await page.evaluate(_SAVE_TOGGLE_JS)
            raise ToolError(
                f"The job was already in the opposite state; no change made."
            )

        verified = await page.evaluate(_VERIFY_SAVE_JS)
        pressed = verified.get("pressed") if isinstance(verified, dict) else None
        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": got, "confirmed": pressed is expect_saved}

    except ToolError:
        raise
    except AuthenticationError as e:
        try:
            await handle_auth_error(e, ctx)
        except Exception as relogin_exc:
            raise_tool_error(relogin_exc, tool_name)
    except Exception as e:
        raise_tool_error(e, tool_name)  # NoReturn
    return {}  # unreachable


async def _apply(ctx: Context, *, tool_name: str, job_url: str) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(job_url, "job_details")
        page = extractor.page

        result = await page.evaluate(_APPLY_JS)
        if not isinstance(result, dict) or result.get("status") not in (
            "opened",
            "external",
        ):
            raise ToolError(
                "No apply control found on this job page; the listing may not "
                "accept applications."
            )

        await ctx.report_progress(progress=100, total=100, message="Complete")
        if result.get("status") == "opened":
            return {"status": "opened", "dialog": True}
        return {"status": "external", "apply_url": result.get("apply_url", "")}

    except ToolError:
        raise
    except AuthenticationError as e:
        try:
            await handle_auth_error(e, ctx)
        except Exception as relogin_exc:
            raise_tool_error(relogin_exc, tool_name)
    except Exception as e:
        raise_tool_error(e, tool_name)  # NoReturn
    return {}  # unreachable


def register_job_actions_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register job action tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Save Job",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"job", "actions"},
    )
    async def save_job(job_url: str, ctx: Context) -> dict[str, Any]:
        """Save a LinkedIn job posting.

        Args:
            job_url: Full URL of the job posting.
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status ("saved") and confirmed flag.
        """
        return await _save_toggle(
            ctx, tool_name="save_job", job_url=job_url, expect_saved=True
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Unsave Job",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"job", "actions"},
    )
    async def unsave_job(job_url: str, ctx: Context) -> dict[str, Any]:
        """Remove a saved LinkedIn job posting from your saved list.

        Args:
            job_url: Full URL of the job posting.
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status ("unsaved") and confirmed flag.
        """
        return await _save_toggle(
            ctx, tool_name="unsave_job", job_url=job_url, expect_saved=False
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Apply To Job",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"job", "actions"},
    )
    async def apply_to_job(job_url: str, ctx: Context) -> dict[str, Any]:
        """Start the application flow for a LinkedIn job posting.

        Args:
            job_url: Full URL of the job posting.
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status ("opened" for Easy Apply or "external" with
            apply_url).
        """
        return await _apply(ctx, tool_name="apply_to_job", job_url=job_url)
