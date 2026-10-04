"""Engagement tools: reactions, comments, replies, reaction counts."""

import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error

logger = logging.getLogger(__name__)

_REACT_JS = """(reaction) => {
  const buttons = Array.from(
    document.querySelectorAll('button, [role="button"]'),
  ).filter((b) => b.offsetParent !== null);
  const like = buttons.find((b) => {
    const label = (
      (b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')
    ).toLowerCase();
    return label.includes('like') || label.includes('react');
  });
  if (!like) return { status: 'not_found' };
  if (reaction && reaction !== 'like') {
    like.dispatchEvent(new Event('mouseover', { bubbles: true }));
    const bar = document.querySelector('[role="toolbar"], .reactions-react-bar');
    const target = bar
      ? Array.from(bar.querySelectorAll('button, [role="button"]')).find((el) => {
          const label = (
            el.getAttribute('aria-label') || el.getAttribute('title') || ''
          ).toLowerCase();
          return label.includes(reaction);
        })
      : null;
    if (target) {
      target.click();
      return { status: 'reacted', reaction: reaction };
    }
  }
  like.click();
  return { status: 'reacted', reaction: 'like' };
}"""

_VERIFY_REACT_JS = """() => {
  const pressed = document.querySelector(
    'button[aria-pressed="true"]',
  );
  return pressed ? { status: 'ok' } : { status: 'unconfirmed' };
}"""

_SET_COMMENT_JS = """(value) => {
  const editors = Array.from(
    document.querySelectorAll('[contenteditable="true"], textarea'),
  ).filter((el) => el.offsetParent !== null);
  if (editors.length === 0) return { status: 'no_editor' };
  const editor = editors[0];
  editor.focus();
  editor.innerText = value;
  editor.dispatchEvent(new Event('input', { bubbles: true }));
  const text = (editor.innerText || '').trim();
  return { status: 'set', text: text };
}"""

_SUBMIT_COMMENT_JS = """() => {
  const buttons = Array.from(document.querySelectorAll('button')).filter(
    (b) => b.offsetParent !== null,
  );
  const post = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('post') || label.includes('comment');
  });
  if (!post) return { status: 'not_found' };
  post.click();
  return { status: 'posted' };
}"""

_OPEN_REPLY_JS = """(index) => {
  const replies = Array.from(
    document.querySelectorAll('button, [role="button"]'),
  ).filter((b) => b.offsetParent !== null);
  const replyControls = replies.filter((b) => {
    const label = (
      (b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')
    ).toLowerCase();
    return label.includes('reply');
  });
  if (index >= replyControls.length) return { status: 'not_found' };
  replyControls[index].click();
  return { status: 'opened' };
}"""

_GET_REACTIONS_JS = """() => {
  const social = Array.from(
    document.querySelectorAll('[aria-label*="reaction"], [aria-label*="like"], span'),
  ).filter((el) => el.offsetParent !== null);
  const counts = social
    .map((el) => (el.innerText || '').trim())
    .find((t) => /\\d+\\s*(reaction|like)/i.test(t));
  const icons = Array.from(
    document.querySelectorAll('[aria-label][class*="reaction"], img[alt]'),
  )
    .map((el) => el.getAttribute('aria-label') || el.getAttribute('alt') || '')
    .filter((t) => t.length > 0)
    .slice(0, 5);
  if (counts === undefined) return { status: 'not_found' };
  return { status: 'ok', counts: counts, top: icons };
}"""


async def _react(
    ctx: Context, *, tool_name: str, post_url: str, reaction: str
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(post_url, "feed")
        page = extractor.page

        reacted = await page.evaluate(_REACT_JS, reaction)
        if not isinstance(reacted, dict) or reacted.get("status") != "reacted":
            raise ToolError(
                "No reaction control found on this post; the URL may not be a "
                "post or LinkedIn did not render the reaction bar."
            )

        verified = await page.evaluate(_VERIFY_REACT_JS)
        status = verified.get("status") if isinstance(verified, dict) else None
        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {
            "status": "reacted",
            "reaction": reacted.get("reaction", reaction),
            "confirmed": status == "ok",
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


async def _comment(
    ctx: Context,
    *,
    tool_name: str,
    post_url: str,
    text: str,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(post_url, "feed")
        page = extractor.page

        set_result = await page.evaluate(_SET_COMMENT_JS, text)
        if not isinstance(set_result, dict) or set_result.get("status") != "set":
            status = (
                set_result.get("status")
                if isinstance(set_result, dict)
                else "unexpected"
            )
            raise ToolError(
                f"Could not write into the comment composer (status: {status})."
            )

        if dry_run:
            return {"status": "dry_run", "text": text}

        posted = await page.evaluate(_SUBMIT_COMMENT_JS)
        if not isinstance(posted, dict) or posted.get("status") != "posted":
            raise ToolError("The comment composer did not expose a post button.")

        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": "commented", "text": text}

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


async def _reply(
    ctx: Context,
    *,
    tool_name: str,
    post_url: str,
    comment_index: int,
    text: str,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(post_url, "feed")
        page = extractor.page

        opened = await page.evaluate(_OPEN_REPLY_JS, comment_index)
        if not isinstance(opened, dict) or opened.get("status") != "opened":
            raise ToolError(
                f"No reply control found at comment index {comment_index}."
            )

        set_result = await page.evaluate(_SET_COMMENT_JS, text)
        if not isinstance(set_result, dict) or set_result.get("status") != "set":
            raise ToolError("Could not write into the reply composer.")

        if dry_run:
            return {"status": "dry_run", "text": text}

        posted = await page.evaluate(_SUBMIT_COMMENT_JS)
        if not isinstance(posted, dict) or posted.get("status") != "posted":
            raise ToolError("The reply composer did not expose a post button.")

        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": "replied", "text": text}

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


async def _get_reactions(
    ctx: Context, *, tool_name: str, post_url: str
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(post_url, "feed")
        page = extractor.page

        result = await page.evaluate(_GET_REACTIONS_JS)
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise ToolError("No reaction counts found on this post.")

        return {
            "status": "ok",
            "counts": result.get("counts", ""),
            "top": result.get("top", []),
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


def register_engagement_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register engagement tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="React To Post",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"post", "actions"},
    )
    async def react_to_post(
        post_url: str, reaction: str, ctx: Context
    ) -> dict[str, Any]:
        """React to a LinkedIn post.

        Args:
            post_url: Full URL of the post.
            reaction: Reaction type, e.g. "like", "celebrate", "love",
                "insightful", "funny", "support". "like" is the default.
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status, reaction, and confirmed flag.
        """
        return await _react(
            ctx, tool_name="react_to_post", post_url=post_url, reaction=reaction
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Comment On Post",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"post", "actions"},
    )
    async def comment_on_post(
        post_url: str, text: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Add a comment to a LinkedIn post.

        Args:
            post_url: Full URL of the post.
            text: Comment body text.
            ctx: FastMCP context for progress reporting.
            dry_run: When True, fill the comment but do not submit.

        Returns:
            Dict with status ("commented" or "dry_run") and text.
        """
        return await _comment(
            ctx,
            tool_name="comment_on_post",
            post_url=post_url,
            text=text,
            dry_run=dry_run,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Reply To Comment",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"post", "actions"},
    )
    async def reply_to_comment(
        post_url: str, comment_index: int, text: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Reply to a comment on a LinkedIn post.

        Args:
            post_url: Full URL of the post.
            comment_index: Zero-based index of the target comment.
            text: Reply body text.
            ctx: FastMCP context for progress reporting.
            dry_run: When True, fill the reply but do not submit.

        Returns:
            Dict with status ("replied" or "dry_run") and text.
        """
        return await _reply(
            ctx,
            tool_name="reply_to_comment",
            post_url=post_url,
            comment_index=comment_index,
            text=text,
            dry_run=dry_run,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Post Reactions",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"post"},
    )
    async def get_post_reactions(post_url: str, ctx: Context) -> dict[str, Any]:
        """Read the reaction summary of a LinkedIn post.

        Args:
            post_url: Full URL of the post.
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status, counts, and top reaction labels.
        """
        return await _get_reactions(
            ctx, tool_name="get_post_reactions", post_url=post_url
        )
