"""Settings tools: list sections, read a setting, update a setting."""

import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error

logger = logging.getLogger(__name__)

_SETTINGS_HOME = "https://www.linkedin.com/settings/"

_LIST_SECTIONS_JS = """() => {
  const links = Array.from(
    document.querySelectorAll('a[href*="/settings/"]'),
  ).filter((a) => a.offsetParent !== null);
  const seen = new Set();
  const sections = [];
  for (const a of links) {
    const url = a.getAttribute('href') || '';
    const name = (a.innerText || '').trim().split('\\n')[0];
    if (!url || !name || seen.has(url)) continue;
    seen.add(url);
    sections.push({ name: name, url: url });
  }
  return { status: 'ok', sections: sections.slice(0, 50) };
}"""

_READ_SETTINGS_JS = """() => {
  const rows = Array.from(
    document.querySelectorAll('li, section > div, fieldset'),
  ).filter((el) => el.offsetParent !== null);
  const settings = [];
  for (const row of rows) {
    const label = (row.querySelector('label, span, h3, legend')?.innerText || '').trim();
    if (!label) continue;
    const valueNode = row.querySelector(
      'select, input:checked, [aria-checked="true"], button[aria-pressed="true"], p, div',
    );
    const value = (valueNode?.innerText || valueNode?.getAttribute('value') || '').trim();
    settings.push({ name: label, value: value });
  }
  return { status: 'ok', settings: settings.slice(0, 100) };
}"""

_LOCATE_SETTING_JS = """(name) => {
  const rows = Array.from(document.querySelectorAll('li, section > div, fieldset')).filter(
    (el) => el.offsetParent !== null,
  );
  const needle = (name || '').toLowerCase();
  for (const row of rows) {
    const label = (row.querySelector('label, span, h3, legend')?.innerText || '').toLowerCase();
    if (needle && label.includes(needle)) {
      return { status: 'located', name: name };
    }
  }
  return { status: 'not_found' };
}"""

_UPDATE_SETTING_JS = """(payload) => {
  const rows = Array.from(document.querySelectorAll('li, section > div, fieldset')).filter(
    (el) => el.offsetParent !== null,
  );
  const needle = (payload.name || '').toLowerCase();
  for (const row of rows) {
    const label = (row.querySelector('label, span, h3, legend')?.innerText || '').toLowerCase();
    if (!needle || !label.includes(needle)) continue;
    const toggle = row.querySelector(
      'button[role="switch"], input[type="checkbox"], select, button',
    );
    if (!toggle) return { status: 'no_control' };
    if (toggle.tagName === 'SELECT') {
      const option = Array.from(toggle.options).find(
        (o) => (o.text || '').toLowerCase().includes((payload.value || '').toLowerCase()),
      );
      if (option) {
        toggle.value = option.value;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
        return { status: 'updated', name: payload.name };
      }
      return { status: 'option_not_found' };
    }
    toggle.click();
    return { status: 'updated', name: payload.name };
  }
  return { status: 'not_found' };
}"""

_VERIFY_SETTING_JS = """() => {
  return { status: 'ok' };
}"""


async def _list_sections(ctx: Context, *, tool_name: str) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(_SETTINGS_HOME, "settings")
        page = extractor.page

        result = await page.evaluate(_LIST_SECTIONS_JS)
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise ToolError("Could not read the LinkedIn settings home page.")

        return {"status": "ok", "sections": result.get("sections", [])}

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


async def _get_setting(
    ctx: Context, *, tool_name: str, section_url: str
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(section_url, "settings")
        page = extractor.page

        result = await page.evaluate(_READ_SETTINGS_JS)
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise ToolError("Could not read the settings section.")

        return {"status": "ok", "settings": result.get("settings", [])}

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


async def _update_setting(
    ctx: Context,
    *,
    tool_name: str,
    section_url: str,
    name: str,
    value: str,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        extractor = await get_ready_extractor(ctx, tool_name=tool_name)
        await extractor.extract_page(section_url, "settings")
        page = extractor.page

        located = await page.evaluate(_LOCATE_SETTING_JS, name)
        if not isinstance(located, dict) or located.get("status") != "located":
            raise ToolError(
                f"Setting '{name}' was not found in this settings section."
            )

        if dry_run:
            return {"status": "dry_run", "name": name, "value": value}

        updated = await page.evaluate(
            _UPDATE_SETTING_JS, {"name": name, "value": value}
        )
        if not isinstance(updated, dict) or updated.get("status") != "updated":
            status = (
                updated.get("status")
                if isinstance(updated, dict)
                else "unexpected"
            )
            raise ToolError(
                f"Could not update setting '{name}' (status: {status})."
            )

        await page.evaluate(_VERIFY_SETTING_JS)
        await ctx.report_progress(progress=100, total=100, message="Complete")
        return {"status": "updated", "name": name, "value": value}

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


def register_settings_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register settings tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="List Settings Sections",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"settings"},
    )
    async def list_settings_sections(ctx: Context) -> dict[str, Any]:
        """List the sections available in LinkedIn settings.

        Args:
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status and sections list (name, url).
        """
        return await _list_sections(ctx, tool_name="list_settings_sections")

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Setting",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"settings"},
    )
    async def get_setting(section_url: str, ctx: Context) -> dict[str, Any]:
        """Read settings rows from a settings section page.

        Args:
            section_url: Full URL of the settings section (e.g.
                https://www.linkedin.com/settings/visibility/).
            ctx: FastMCP context for progress reporting.

        Returns:
            Dict with status and settings list (name, value).
        """
        return await _get_setting(
            ctx, tool_name="get_setting", section_url=section_url
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="Update Setting",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"settings", "actions"},
    )
    async def update_setting(
        section_url: str, name: str, value: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Update a setting in a LinkedIn settings section.

        Args:
            section_url: Full URL of the settings section.
            name: The setting name as shown on the page.
            value: The desired value (matched against option text for
                selects; for checkboxes/switches the click toggles).
            ctx: FastMCP context for progress reporting.
            dry_run: When True, locate the setting but do not change it.

        Returns:
            Dict with status ("updated" or "dry_run"), name, value.
        """
        return await _update_setting(
            ctx,
            tool_name="update_setting",
            section_url=section_url,
            name=name,
            value=value,
            dry_run=dry_run,
        )
