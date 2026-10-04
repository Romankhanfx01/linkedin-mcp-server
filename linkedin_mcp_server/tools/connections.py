"""Connection management tools: pending invites, accept/decline, withdraw."""

import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error

logger = logging.getLogger(__name__)

_INVITE_MANAGER_URL = "https://www.linkedin.com/mynetwork/invitation-manager/"

_LIST_INVITATIONS_JS = """() => {
  const rows = Array.from(
    document.querySelectorAll('li, [data-view-name], section li'),
  ).filter((el) => el.offsetParent !== null);
  const invitations = [];
  for (const row of rows) {
    const buttons = row.querySelectorAll('button');
    if (buttons.length === 0) continue;
    const textNodes = Array.from(row.querySelectorAll('span, a, p'))
      .map((n) => (n.innerText || '').trim())
      .filter((t) => t.length > 0);
    if (textNodes.length === 0) continue;
    invitations.push({
      name: textNodes[0] || '',
      headline: textNodes[1] || '',
      time: textNodes.length > 2 ? textNodes[textNodes.length - 1] : '',
    });
  }
  return { status: 'ok', invitations: invitations.slice(0, 50) };
}"""

_CLICK_INVITE_ACTION_JS = """(payload) => {
  const name = (payload.name || '').toLowerCase();
  const action = payload.action; // 'accept' or 'decline'
  const rows = Array.from(document.querySelectorAll('li')).filter(
    (el) => el.offsetParent !== null,
  );
  for (const row of rows) {
    const text = (row.innerText || '').toLowerCase();
    if (name && !text.includes(name)) continue;
    const buttons = Array.from(row.querySelectorAll('button'));
    const target = buttons.find((b) => {
      const label = (
        (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
      ).toLowerCase();
      if (action === 'accept') return label.includes('accept');
      return label.includes('ignore') || label.includes('decline') || label.includes('reject');
    });
    if (target) {
      target.click();
      const rowName = text.split('\\n')[0] || payload.name;
      return { status: 'clicked', name: rowName };
    }
  }
  return { status: 'not_found' };
}"""

_VERIFY_INVITE_DISMISSED_JS = """(name) => {
  const rows = Array.from(document.querySelectorAll('li')).filter(
    (el) => el.offsetParent !== null,
  );
  const still = rows.some((row) => {
    const text = (row.innerText || '').toLowerCase();
    return name && text.includes(name.toLowerCase());
  });
  return still ? { status: 'unconfirmed' } : { status: 'ok' };
}"""

_OPEN_SENT_TAB_JS = """() => {
  const tabs = Array.from(
    document.querySelectorAll('button, a, [role="tab"]'),
  ).filter((el) => el.offsetParent !== null);
  const sent = tabs.find((el) => {
    const label = (
      (el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('sent');
  });
  if (!sent) return { status: 'not_found' };
  sent.click();
  return { status: 'sent_tab_opened' };
}"""

_WITHDRAW_JS = """(name) => {
  const rows = Array.from(document.querySelectorAll('li')).filter(
    (el) => el.offsetParent !== null,
  );
  for (const row of rows) {
    const text = (row.innerText || '').toLowerCase();
    if (name && !text.includes((name || '').toLowerCase())) continue;
    const buttons = Array.from(row.querySelectorAll('button'));
    const withdraw = buttons.find((b) => {
      const label = (
        (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
      ).toLowerCase();
      return label.includes('withdraw');
    });
    if (withdraw) {
      withdraw.click();
      return { status: 'withdraw_clicked', name: name };
    }
  }
  return { status: 'not_found' };
}"""

_CONFIRM_WITHDRAW_JS = """() => {
  const buttons = Array.from(document.querySelectorAll('button')).filter(
    (b) => b.offsetParent !== null,
  );
  const confirm = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('withdraw') || label.includes('confirm');
  });
  if (!confirm) return { status: 'not_found' };
  confirm.click();
  return { status: 'confirmed' };
}"""


async def _list_invitations(ctx: Context, *, tool_name: str) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(_INVITE_MANAGER_URL, "mynetwork")
        page = extractor.page

        result = await page.evaluate(_LIST_INVITATIONS_JS)
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise ToolError("Could not read the invitation manager page.")

        return {"status": "ok", "invitations": result.get("invitations", [])}

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


async def _invitation_action(
    ctx: Context,
    *,
    tool_name: str,
    name: str,
    action: str,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(_INVITE_MANAGER_URL, "mynetwork")
        page = extractor.page

        clicked = await page.evaluate(
            _CLICK_INVITE_ACTION_JS, {"name": name, "action": action}
        )
        if not isinstance(clicked, dict) or clicked.get("status") != "clicked":
            raise ToolError(
                f"No pending invitation matching '{name}' with an {action} control "
                "was found."
            )

        if dry_run:
            return {"status": "dry_run", "name": name, "action": action}

        verified = await page.evaluate(_VERIFY_INVITE_DISMISSED_JS, name)
        status = verified.get("status") if isinstance(verified, dict) else None
        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {
            "status": "accepted" if action == "accept" else "declined",
            "name": name,
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


async def _withdraw(
    ctx: Context, *, tool_name: str, name: str, dry_run: bool
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(_INVITE_MANAGER_URL, "mynetwork")
        page = extractor.page

        tab = await page.evaluate(_OPEN_SENT_TAB_JS)
        if not isinstance(tab, dict) or tab.get("status") != "sent_tab_opened":
            raise ToolError("The invitation manager did not expose a Sent tab.")

        clicked = await page.evaluate(_WITHDRAW_JS, name)
        if not isinstance(clicked, dict) or clicked.get("status") != "withdraw_clicked":
            raise ToolError(
                f"No sent invitation matching '{name}' with a withdraw control "
                "was found."
            )

        if dry_run:
            return {"status": "dry_run", "name": name}

        confirmed = await page.evaluate(_CONFIRM_WITHDRAW_JS)
        if not isinstance(confirmed, dict) or confirmed.get("status") != "confirmed":
            raise ToolError("The withdraw confirmation dialog did not render.")

        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": "withdrawn", "name": name}

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


def register_connections_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register connection management tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="List Pending Invitations",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"connection"},
    )
    async def list_pending_invitations(ctx: Context) -> dict[str, Any]:
        """List incoming pending connection invitations.

        Args:
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status and invitations list (name, headline, time).
        """
        return await _list_invitations(ctx, tool_name="list_pending_invitations")

    @mcp.tool(
        timeout=tool_timeout,
        title="Accept Invitation",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"connection", "actions"},
    )
    async def accept_invitation(
        name: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Accept a pending connection invitation by the sender's name.

        Args:
            name: Sender display name as shown in the invitation row.
            ctx: FastMCP context for progress reporting.
            dry_run: When True, locate the control but do not click.

        Returns:
            Dict with status ("accepted" or "dry_run"), name, confirmed.
        """
        return await _invitation_action(
            ctx,
            tool_name="accept_invitation",
            name=name,
            action="accept",
            dry_run=dry_run,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Decline Invitation",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"connection", "actions"},
    )
    async def decline_invitation(
        name: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Decline (ignore) a pending connection invitation by sender name.

        Args:
            name: Sender display name as shown in the invitation row.
            ctx: FastMCP context for progress reporting.
            dry_run: When True, locate the control but do not click.

        Returns:
            Dict with status ("declined" or "dry_run"), name, confirmed.
        """
        return await _invitation_action(
            ctx,
            tool_name="decline_invitation",
            name=name,
            action="decline",
            dry_run=dry_run,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Withdraw Connection Request",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"connection", "actions"},
    )
    async def withdraw_connection_request(
        name: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Withdraw a previously sent connection request.

        Args:
            name: Target display name as shown in the sent invitations list.
            ctx: FastMCP context for progress reporting.
            dry_run: When True, locate the control but do not click.

        Returns:
            Dict with status ("withdrawn" or "dry_run") and name.
        """
        return await _withdraw(
            ctx, tool_name="withdraw_connection_request", name=name, dry_run=dry_run
        )
