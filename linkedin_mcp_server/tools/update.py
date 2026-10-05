"""LinkedIn profile field editing tools (headline and about)."""

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

_OPEN_EDIT_JS = """(field) => {
  const controls = Array.from(
    document.querySelectorAll('main button, main a, main [role="button"]'),
  );
  let match;
  if (field === 'headline') {
    match = controls.find((el) => {
      const label = (
        el.getAttribute('aria-label') || el.getAttribute('title') || ''
      ).toLowerCase();
      return el.tagName === 'BUTTON' && label === 'edit';
    });
    if (!match) {
      match = controls.find((el) => {
        const label = (
          el.getAttribute('aria-label') || el.getAttribute('title') || ''
        ).toLowerCase();
        return label === 'edit profile' || label.includes('edit intro');
      });
    }
  } else {
    match = controls.find((el) => {
      const label = (
        el.getAttribute('aria-label') || el.getAttribute('title') || ''
      ).toLowerCase();
      return label.includes('edit about') || label.includes('edit summary');
    });
  }
  if (!match) return { status: 'not_found' };
  match.click();
  return { status: 'opened' };
}"""

_SET_FIELD_JS = """(payload) => {
  const { value, field } = payload;
  const editors = Array.from(
    document.querySelectorAll('textarea, [contenteditable], input[type="text"], [role="textbox"]'),
  ).filter((el) => el.offsetParent !== null);
  if (editors.length === 0) return { status: 'no_editor' };
  let editor = null;
  if (field === 'headline') {
    editor = editors.find((el) => {
      const labelText = (
        el.closest('label, fieldset, div')?.querySelector('label, span')
          ?.innerText || ''
      ).toLowerCase();
      const hay = [
        el.getAttribute('aria-label') || '',
        el.getAttribute('placeholder') || '',
        el.getAttribute('name') || '',
        el.getAttribute('id') || '',
        labelText,
      ].join(' ').toLowerCase();
      return hay.includes('headline') || hay.includes('intro');
    }) || null;
    if (!editor) editor = editors.length === 1 ? editors[0] : null;
  } else {
    editor = editors.find((el) => {
      const labelText = (
        el.closest('label, fieldset, div')?.querySelector('label, span')
          ?.innerText || ''
      ).toLowerCase();
      const hay = [
        el.getAttribute('aria-label') || '',
        el.getAttribute('placeholder') || '',
        el.getAttribute('name') || '',
        el.getAttribute('id') || '',
        labelText,
      ].join(' ').toLowerCase();
      return hay.includes('summary') || hay.includes('about');
    }) || null;
    if (!editor && editors.length === 1) editor = editors[0];
  }
  if (!editor) return { status: 'ambiguous_editor' };
  editor.focus();
  if ('value' in editor) {
    editor.value = value;
  } else {
    editor.innerText = value;
  }
  editor.dispatchEvent(new Event('input', { bubbles: true }));
  editor.dispatchEvent(new Event('change', { bubbles: true }));
  const text = 'value' in editor ? editor.value : editor.innerText;
  return { status: 'set', text: text };
}"""

_SAVE_JS = """() => {
  const buttons = Array.from(
    document.querySelectorAll('button, [role="button"]'),
  );
  const save = buttons.find((b) => {
    const label = (
      (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
    ).toLowerCase();
    return label.includes('save');
  });
  if (!save) return { status: 'save_not_found' };
  save.click();
  return { status: 'saved' };
}"""

_READ_BACK_JS = """(field) => {
  const normalize = (v) => (v || '').replace(/\\s+/g, ' ').trim();
  if (field === 'about') {
    const headings = Array.from(
      document.querySelectorAll('main h2, main h3'),
    );
    for (const h of headings) {
      const t = normalize(h.innerText || h.textContent).toLowerCase();
      if (t === 'about') {
        const container = h.parentElement;
        if (container) {
          const paras = Array.from(container.querySelectorAll('p, span'));
          for (const p of paras) {
            const text = normalize(p.innerText || p.textContent);
            if (text) return { status: 'ok', text: text };
          }
        }
        return { status: 'not_found', text: '' };
      }
    }
    return { status: 'not_found', text: '' };
  }
  const header = document.querySelector('main h1');
  if (header && header.parentElement) {
    const nodes = Array.from(
      header.parentElement.querySelectorAll('p, span, div'),
    );
    for (const n of nodes) {
      const text = normalize(n.innerText || n.textContent);
      if (text) return { status: 'ok', text: text };
    }
  }
  return { status: 'not_found', text: '' };
}"""


def _normalize(value: str) -> str:
    return " ".join(value.split())


async def _update_field(
    ctx: Context,
    *,
    tool_name: str,
    url: str,
    field: str,
    new_value: str,
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        logger.info("Updating %s for %s", field, url)

        await ctx.report_progress(
            progress=0, total=100, message=f"Loading profile for {field} edit"
        )
        await extractor.extract_page(url, "main_profile")

        page = extractor.page

        opened = await page.evaluate(_OPEN_EDIT_JS, field)
        if not isinstance(opened, dict) or opened.get("status") != "opened":
            raise ToolError(
                f"No editable {field} control found on this profile page. "
                "The profile may not be your own, or LinkedIn did not render "
                "the edit control."
            )

        await asyncio.sleep(2.0)

        set_result = await page.evaluate(
            _SET_FIELD_JS, {"value": new_value, "field": field}
        )
        if not isinstance(set_result, dict) or set_result.get("status") != "set":
            await asyncio.sleep(2.0)
            set_result = await page.evaluate(
                _SET_FIELD_JS, {"value": new_value, "field": field}
            )
        if not isinstance(set_result, dict) or set_result.get("status") != "set":
            status = (
                set_result.get("status")
                if isinstance(set_result, dict)
                else "unexpected"
            )
            raise ToolError(
                f"Could not write the new {field} text into the editor "
                f"(status: {status})."
            )

        saved = await page.evaluate(_SAVE_JS)
        if not isinstance(saved, dict) or saved.get("status") != "saved":
            raise ToolError(f"The {field} edit dialog did not expose a save control.")

        await ctx.report_progress(
            progress=50, total=100, message=f"Verifying {field} update"
        )
        read_back = await page.evaluate(_READ_BACK_JS, field)
        text = read_back.get("text", "") if isinstance(read_back, dict) else ""
        if _normalize(new_value) not in _normalize(text):
            raise ToolError(
                f"The updated {field} text is not visible on the profile page "
                "after saving; the change could not be confirmed."
            )

        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {
            "url": url,
            "field": field,
            "value": new_value,
            "confirmed_text": text,
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
    return {}  # unreachable; keeps type checkers satisfied


def register_update_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register profile-field editing tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Update Headline",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"person", "actions"},
    )
    async def update_headline(
        url: str, new_headline: str, ctx: Context
    ) -> dict[str, Any]:
        """Update the headline of the LinkedIn profile at the given URL.

        Args:
            url: Full LinkedIn profile URL to edit (must be your own profile).
            new_headline: The new headline text.
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with url, field, value, and confirmed_text (the visible
            paragraph text re-read from the profile card after saving).
        """
        return await _update_field(
            ctx,
            tool_name="update_headline",
            url=url,
            field="headline",
            new_value=new_headline,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Update About",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"person", "actions"},
    )
    async def update_about(url: str, new_about: str, ctx: Context) -> dict[str, Any]:
        """Update the About section of the LinkedIn profile at the given URL.

        Args:
            url: Full LinkedIn profile URL to edit (must be your own profile).
            new_about: The new About section text.
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with url, field, value, and confirmed_text (the visible
            paragraph text re-read from the profile card after saving).
        """
        return await _update_field(
            ctx,
            tool_name="update_about",
            url=url,
            field="about",
            new_value=new_about,
        )
