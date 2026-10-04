"""Notifications tools: read list, mark all read."""

import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error

logger = logging.getLogger(__name__)

_NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"

_LIST_NOTIFICATIONS_JS = """() => {
  const items = Array.from(
    document.querySelectorAll('li, [data-finite-scroll-hotspot], section li'),
  ).filter((el) => el.offsetParent !== null);
  const rows = [];
  for (const item of items) {
    const text = (item.innerText || '').trim();
    if (!text) continue;
    const dot = item.querySelector(
      '[class*="unread"], [aria-label*="unread"], [data-test-unread]',
    );
    rows.push({ text: text.split('\\n')[0], unread: dot !== null });
  }
  return { status: 'ok', notifications: rows.slice(0, 50) };
}"""

_MARK_ALL_READ_JS = """() => {
  const controls = Array.from(
    document.querySelectorAll('button, a, [role="button"]'),
  ).filter((el) => el.offsetParent !== null);
  const target = controls.find((el) => {
    const label = (
      (el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('mark all') || label.includes('mark as read');
  });
  if (!target) return { status: 'not_found' };
  target.click();
  return { status: 'clicked' };
}"""

_VERIFY_MARKED_READ_JS = """() => {
  const unread = document.querySelectorAll(
    '[class*="unread"], [aria-label*="unread"], [data-test-unread]',
  );
  return unread.length === 0
    ? { status: 'ok' }
    : { status: 'unconfirmed', remaining: unread.length };
}"""


async def _get_notifications(ctx: Context, *, tool_name: str) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(_NOTIFICATIONS_URL, "notifications")
        page = extractor.page

        result = await page.evaluate(_LIST_NOTIFICATIONS_JS)
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise ToolError("Could not read the notifications page.")

        return {
            "status": "ok",
            "notifications": result.get("notifications", []),
        }

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


async def _mark_read(
    ctx: Context, *, tool_name: str, dry_run: bool
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(_NOTIFICATIONS_URL, "notifications")
        page = extractor.page

        clicked = await page.evaluate(_MARK_ALL_READ_JS)
        if not isinstance(clicked, dict) or clicked.get("status") != "clicked":
            raise ToolError(
                "No mark-all-read control found on the notifications page."
            )

        if dry_run:
            return {"status": "dry_run"}

        verified = await page.evaluate(_VERIFY_MARKED_READ_JS)
        ok = isinstance(verified, dict) and verified.get("status") == "ok"
        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": "marked_read", "confirmed": ok}

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


def register_notifications_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register notification tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Notifications",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"notifications"},
    )
    async def get_notifications(ctx: Context) -> dict[str, Any]:
        """List LinkedIn notifications.

        Args:
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status and notifications list (text, unread).
        """
        return await _get_notifications(ctx, tool_name="get_notifications")

    @mcp.tool(
        timeout=tool_timeout,
        title="Mark Notifications Read",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"notifications", "actions"},
    )
    async def mark_notifications_read(
        ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Mark all LinkedIn notifications as read.

        Args:
            ctx: FastMCP context for progress reporting.
            dry_run: When True, locate the control but do not click.

        Returns:
            Dict with status ("marked_read" or "dry_run").
        """
        return await _mark_read(
            ctx, tool_name="mark_notifications_read", dry_run=dry_run
        )
