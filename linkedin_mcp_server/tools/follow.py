"""Follow/unfollow tools for people and companies."""

import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error

logger = logging.getLogger(__name__)

_FOLLOW_TOGGLE_JS = """(want_following) => {
  const buttons = Array.from(document.querySelectorAll('button')).filter(
    (b) => b.offsetParent !== null,
  );
  const target = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('follow');
  });
  if (!target) return { status: 'not_found' };
  const label = (
    (target.innerText || '') + ' ' + (target.getAttribute('aria-label') || '')
  ).toLowerCase();
  const isFollowing = label.includes('following') || label.includes('unfollow');
  if (isFollowing === want_following) {
    return want_following
      ? { status: 'already_following' }
      : { status: 'already_not_following' };
  }
  target.click();
  return want_following
    ? { status: 'followed', following: true }
    : { status: 'unfollowed', following: false };
}"""

_VERIFY_FOLLOW_JS = """(want_following) => {
  const buttons = Array.from(document.querySelectorAll('button')).filter(
    (b) => b.offsetParent !== null,
  );
  const target = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('follow');
  });
  if (!target) return { status: 'not_found' };
  const label = (
    (target.innerText || '') + ' ' + (target.getAttribute('aria-label') || '')
  ).toLowerCase();
  const isFollowing = label.includes('following') || label.includes('unfollow');
  return {
    status: 'ok',
    following: isFollowing === want_following,
  };
}"""


async def _follow_toggle(
    ctx: Context,
    *,
    tool_name: str,
    url: str,
    section: str,
    want_following: bool,
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(url, section)
        page = extractor.page

        toggled = await page.evaluate(_FOLLOW_TOGGLE_JS, want_following)
        if not isinstance(toggled, dict):
            raise ToolError("Unexpected page response while toggling follow.")

        if toggled.get("status") == "not_found":
            raise ToolError(
                "No follow control found on this page; the URL may be invalid."
            )

        if toggled.get("status") in ("already_following", "already_not_following"):
            return {"status": toggled["status"]}

        verified = await page.evaluate(_VERIFY_FOLLOW_JS, want_following)
        ok = (
            isinstance(verified, dict)
            and verified.get("status") == "ok"
            and verified.get("following") is True
        )
        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": toggled["status"], "confirmed": ok}

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


def register_follow_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register follow/unfollow tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Follow Person",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"person", "actions"},
    )
    async def follow_person(linkedin_username: str, ctx: Context) -> dict[str, Any]:
        """Follow a LinkedIn member.

        Args:
            linkedin_username: LinkedIn username (e.g. "alice").
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status ("followed", "already_following").
        """
        return await _follow_toggle(
            ctx,
            tool_name="follow_person",
            url=f"https://www.linkedin.com/in/{linkedin_username}/",
            section="main_profile",
            want_following=True,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Unfollow Person",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"person", "actions"},
    )
    async def unfollow_person(linkedin_username: str, ctx: Context) -> dict[str, Any]:
        """Unfollow a LinkedIn member.

        Args:
            linkedin_username: LinkedIn username (e.g. "alice").
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status ("unfollowed", "already_not_following").
        """
        return await _follow_toggle(
            ctx,
            tool_name="unfollow_person",
            url=f"https://www.linkedin.com/in/{linkedin_username}/",
            section="main_profile",
            want_following=False,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Follow Company",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"company", "actions"},
    )
    async def follow_company(company_slug: str, ctx: Context) -> dict[str, Any]:
        """Follow a LinkedIn company page.

        Args:
            company_slug: LinkedIn company URL slug (e.g. "acme-corp").
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status ("followed", "already_following").
        """
        return await _follow_toggle(
            ctx,
            tool_name="follow_company",
            url=f"https://www.linkedin.com/company/{company_slug}/",
            section="company",
            want_following=True,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Unfollow Company",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"company", "actions"},
    )
    async def unfollow_company(company_slug: str, ctx: Context) -> dict[str, Any]:
        """Unfollow a LinkedIn company page.

        Args:
            company_slug: LinkedIn company URL slug (e.g. "acme-corp").
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status ("unfollowed", "already_not_following").
        """
        return await _follow_toggle(
            ctx,
            tool_name="unfollow_company",
            url=f"https://www.linkedin.com/company/{company_slug}/",
            section="company",
            want_following=False,
        )
