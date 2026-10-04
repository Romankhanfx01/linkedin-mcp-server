"""Temporary diagnostic tool to dump profile page edit controls."""

import logging
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.dependencies import get_ready_extractor

logger = logging.getLogger(__name__)

_DUMP_CONTROLS_JS = """() => {
  const controls = Array.from(
    document.querySelectorAll('main button, main a, main [role="button"]'),
  ).filter((el) => el.offsetParent !== null);
  const editors = Array.from(
    document.querySelectorAll('textarea, [contenteditable], input[type="text"], [role="textbox"], input, select'),
  ).filter((el) => el.offsetParent !== null);
  return {
    status: 'ok',
    controls: controls.slice(0, 60).map((el) => ({
      tag: el.tagName.toLowerCase(),
      aria_label: el.getAttribute('aria-label'),
      title: el.getAttribute('title'),
      text: (el.innerText || '').trim().split('\\n')[0].slice(0, 60),
      href: el.getAttribute('href'),
    })),
    editors: editors.slice(0, 40).map((el) => ({
      tag: el.tagName.toLowerCase(),
      aria_label: el.getAttribute('aria-label'),
      placeholder: el.getAttribute('placeholder'),
      name: el.getAttribute('name'),
      id: el.getAttribute('id'),
      preceding_label: el.closest('label, fieldset, div')?.querySelector('label, span')?.innerText?.trim()?.slice(0, 50),
      value_preview: (el.value || el.innerText || '').trim().slice(0, 50),
    })),
  };
}"""


def register_debug_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register diagnostic tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Debug Profile Controls",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"debug"},
    )
    async def debug_profile_controls(
        ctx: Context, url: str = "https://www.linkedin.com/in/me/"
    ) -> dict[str, Any]:
        """Dump visible button/link controls on a profile page."""
        extractor = await get_ready_extractor(ctx, tool_name="debug_profile_controls")
        await extractor.extract_page(url, "main_profile")
        page = extractor.page
        result = await page.evaluate(_DUMP_CONTROLS_JS)
        return result if isinstance(result, dict) else {"status": "unexpected"}
