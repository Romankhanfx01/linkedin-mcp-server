"""Posting/content mutation tools: create, delete, create-with-image."""

import asyncio
import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error

logger = logging.getLogger(__name__)

_OPEN_COMPOSER_JS = """() => {
  const controls = Array.from(
    document.querySelectorAll('button, [role="button"], a, div, span'),
  );
  const matches = controls.filter((el) => {
    const label = (
      el.getAttribute('aria-label') ||
      el.getAttribute('title') ||
      (el.innerText || '').trim()
    ).toLowerCase();
    return label.includes('start a post') || label.includes('create a post');
  });
  if (matches.length === 0) return { status: 'not_found' };
  // Prefer the deepest match (the actual placeholder/container that is
  // clicked), falling back to the first in DOM order.
  const match = matches.reduce((best, el) =>
    el.querySelectorAll('*').length < best.querySelectorAll('*').length
      ? el
      : best,
  );
  match.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  return { status: 'opened' };
}"""

_SET_POST_TEXT_JS = """(value) => {
  const editors = Array.from(
    document.querySelectorAll('textarea, [contenteditable], input[type="text"], [role="textbox"]'),
  ).filter((el) => el.offsetParent !== null);
  if (editors.length === 0) return { status: 'no_editor' };
  const editor = editors[0];
  editor.focus();
  editor.innerText = value;
  editor.dispatchEvent(new Event('input', { bubbles: true }));
  const text = (editor.innerText || '').trim();
  return { status: 'set', text: text };
}"""

_SUBMIT_POST_JS = """() => {
  const dialogs = Array.from(
    document.querySelectorAll('[role="dialog"], dialog[open]'),
  );
  for (const d of dialogs) {
    const buttons = Array.from(d.querySelectorAll('button'));
    const post = buttons.find((b) => {
      const label = (
        (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
      ).toLowerCase();
      return label.includes('post');
    });
    if (post) {
      post.click();
      return { status: 'posted' };
    }
  }
  return { status: 'post_not_found' };
}"""

_VERIFY_COMPOSER_CLOSED_JS = """() => {
  const dialogs = Array.from(
    document.querySelectorAll('[role="dialog"], dialog[open]'),
  ).filter((d) => d.offsetParent !== null);
  return dialogs.length === 0
    ? { status: 'ok' }
    : { status: 'still_open' };
}"""

_OPEN_POST_MENU_JS = """() => {
  const menus = Array.from(
    document.querySelectorAll('button[aria-haspopup="menu"], button[aria-expanded]'),
  ).filter((b) => b.offsetParent !== null);
  const post = menus.find((b) => {
    const label = (
      b.getAttribute('aria-label') || b.getAttribute('title') || ''
    ).toLowerCase();
    return label.includes('post') || label.includes('more') || label === '';
  });
  const target = post || menus[0];
  if (!target) return { status: 'not_found' };
  target.click();
  return { status: 'opened' };
}"""

_CLICK_DELETE_JS = """() => {
  const items = Array.from(
    document.querySelectorAll('[role="menuitem"], button, a'),
  ).filter((el) => el.offsetParent !== null);
  const del = items.find((el) => {
    const label = (
      (el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('delete');
  });
  if (!del) return { status: 'not_found' };
  del.click();
  return { status: 'delete_clicked' };
}"""

_CONFIRM_DELETE_JS = """() => {
  const buttons = Array.from(document.querySelectorAll('button')).filter(
    (b) => b.offsetParent !== null,
  );
  const del = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('delete');
  });
  if (!del) return { status: 'not_found' };
  del.click();
  return { status: 'confirmed' };
}"""


async def _create_post(
    ctx: Context,
    *,
    tool_name: str,
    text: str,
    image_path: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page("https://www.linkedin.com/feed/", "feed")
        page = extractor.page

        opened = await page.evaluate(_OPEN_COMPOSER_JS)
        if not isinstance(opened, dict) or opened.get("status") != "opened":
            raise ToolError(
                "Could not open the LinkedIn post composer; the feed page did "
                "not expose a post creation control."
            )

        await asyncio.sleep(2.0)

        set_result = await page.evaluate(_SET_POST_TEXT_JS, text)
        if not isinstance(set_result, dict) or set_result.get("status") != "set":
            await asyncio.sleep(2.0)
            set_result = await page.evaluate(_SET_POST_TEXT_JS, text)
        if not isinstance(set_result, dict) or set_result.get("status") != "set":
            status = (
                set_result.get("status")
                if isinstance(set_result, dict)
                else "unexpected"
            )
            raise ToolError(
                f"Could not write text into the post composer (status: {status})."
            )

        if image_path is not None:
            await page.set_input_files('input[type="file"]', image_path)

        if dry_run:
            return {"status": "dry_run", "text": text}

        submitted = await page.evaluate(_SUBMIT_POST_JS)
        if not isinstance(submitted, dict) or submitted.get("status") != "posted":
            status = (
                submitted.get("status")
                if isinstance(submitted, dict)
                else "unexpected"
            )
            raise ToolError(f"The post dialog has no Post button (status: {status}).")

        await ctx.report_progress(progress=80, total=100, message="Verifying post")
        verified = await page.evaluate(_VERIFY_COMPOSER_CLOSED_JS)
        if not isinstance(verified, dict) or verified.get("status") != "ok":
            raise ToolError(
                "The post composer is still open after submitting; the post "
                "could not be confirmed."
            )

        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": "posted", "text": text}

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


async def _delete_post(
    ctx: Context, *, tool_name: str, post_url: str, dry_run: bool
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(post_url, "feed")
        page = extractor.page

        opened = await page.evaluate(_OPEN_POST_MENU_JS)
        if not isinstance(opened, dict) or opened.get("status") != "opened":
            raise ToolError(
                "No post actions menu was found on this page; the URL may not "
                "be a post you control."
            )

        clicked = await page.evaluate(_CLICK_DELETE_JS)
        if not isinstance(clicked, dict) or clicked.get("status") != "delete_clicked":
            raise ToolError("The post menu did not expose a delete option.")

        if dry_run:
            return {"status": "dry_run", "url": post_url}

        confirmed = await page.evaluate(_CONFIRM_DELETE_JS)
        if not isinstance(confirmed, dict) or confirmed.get("status") != "confirmed":
            raise ToolError("The delete confirmation dialog did not expose a delete button.")

        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": "deleted", "url": post_url}

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


def register_posts_actions_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register posting/content mutation tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Create Post",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"post", "actions"},
    )
    async def create_post(text: str, ctx: Context, dry_run: bool = False) -> dict[str, Any]:
        """Create a new text post on LinkedIn.

        Args:
            text: The post body text.
            ctx: FastMCP context for progress reporting.
            dry_run: When True, compose the post but do not publish.

        Returns:
            Dict with status ("posted" or "dry_run") and text.
        """
        return await _create_post(
            ctx, tool_name="create_post", text=text, image_path=None, dry_run=dry_run
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Create Post With Image",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"post", "actions"},
    )
    async def create_post_with_image(
        text: str, image_path: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Create a new LinkedIn post with an attached image.

        Args:
            text: The post body text.
            image_path: Local path to the image file to attach.
            ctx: FastMCP context for progress reporting.
            dry_run: When True, compose the post but do not publish.

        Returns:
            Dict with status and text.
        """
        return await _create_post(
            ctx,
            tool_name="create_post_with_image",
            text=text,
            image_path=image_path,
            dry_run=dry_run,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Delete Post",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"post", "actions"},
    )
    async def delete_post(
        post_url: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Delete one of your LinkedIn posts.

        Args:
            post_url: Full URL of the post (e.g. /feed/update/urn:li:...).
            ctx: FastMCP context for progress reporting.
            dry_run: When True, navigate to the delete confirmation but do not confirm.

        Returns:
            Dict with status ("deleted" or "dry_run") and url.
        """
        return await _delete_post(
            ctx, tool_name="delete_post", post_url=post_url, dry_run=dry_run
        )
