"""Temporary diagnostic tool to dump profile page edit controls."""

import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

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
        ctx: Context,
        url: str = "https://www.linkedin.com/in/me/",
        after_click_aria_label: str | None = None,
    ) -> dict[str, Any]:
        """Dump visible button/link controls on a profile page."""
        extractor = await get_ready_extractor(ctx, tool_name="debug_profile_controls")
        await extractor.extract_page(url, "main_profile")
        page = extractor.page
        if after_click_aria_label:
            await page.evaluate(
                """(label) => {
                  const els = Array.from(
                    document.querySelectorAll('main button, main a, main [role="button"], main div, main span'),
                  ).filter((el) => el.offsetParent !== null);
                  const needle = (label || '').toLowerCase();
                  const target = els.find((el) => {
                    const t = (
                      (el.getAttribute('aria-label') || '') + ' ' +
                      (el.getAttribute('title') || '') + ' ' +
                      (el.innerText || '')
                    ).toLowerCase();
                    return t.includes(needle);
                  });
                  if (target) {
                    target.click();
                    return { status: 'clicked' };
                  }
                  return { status: 'not_found' };
                }""",
                after_click_aria_label,
            )
            import asyncio as _asyncio

            await _asyncio.sleep(2)
        result = await page.evaluate(_DUMP_CONTROLS_JS)
        return result if isinstance(result, dict) else {"status": "unexpected"}

    @mcp.tool(
        timeout=tool_timeout,
        title="Remove Skill",
        annotations={"destructiveHint": True, "openWorldHint": True},
        tags={"debug"},
    )
    async def remove_skill(
        skill_name: str, ctx: Context, dry_run: bool = False
    ) -> dict[str, Any]:
        """Remove a skill from the profile's skills section."""
        extractor = await get_ready_extractor(ctx, tool_name="remove_skill")
        await extractor.extract_page(
            "https://www.linkedin.com/in/muhammad-roman-dev/details/skills/",
            "main_profile",
        )
        page = extractor.page
        opened = await page.evaluate(
            """(name) => {
              const anchors = Array.from(
                document.querySelectorAll('a[aria-label*="Edit"]'),
              );
              const target = anchors.find((a) => {
                const l = (a.getAttribute('aria-label') || '').toLowerCase();
                return l.includes((name || '').toLowerCase());
              });
              if (!target) return { status: 'not_found' };
              target.click();
              return { status: 'clicked' };
            }""",
            skill_name,
        )
        if not isinstance(opened, dict) or opened.get("status") != "clicked":
            raise ToolError(f"Skill '{skill_name}' edit control not found.")
        import asyncio as _asyncio

        await _asyncio.sleep(2)
        deleted = await page.evaluate(
            """() => {
              const btns = Array.from(document.querySelectorAll('button')).filter(
                (b) => b.offsetParent !== null,
              );
              const del = btns.find((b) => {
                const l = (
                  (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
                ).toLowerCase();
                return l.includes('delete');
              });
              if (!del) return { status: 'no_delete' };
              del.click();
              return { status: 'clicked' };
            }"""
        )
        if not isinstance(deleted, dict) or deleted.get("status") != "clicked":
            raise ToolError(f"Delete control for '{skill_name}' not found.")
        if dry_run:
            return {"status": "dry_run", "skill": skill_name}
        await _asyncio.sleep(2)
        confirmed = await page.evaluate(
            """() => {
              const btns = Array.from(document.querySelectorAll('button')).filter(
                (b) => b.offsetParent !== null,
              );
              const ok = btns.find((b) => {
                const l = (
                  (b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')
                ).toLowerCase();
                return l.includes('delete') || l.includes('confirm');
              });
              if (!ok) return { status: 'no_confirm' };
              ok.click();
              return { status: 'confirmed' };
            }"""
        )
        return {
            "status": "removed",
            "skill": skill_name,
            "confirmed": confirmed.get("status") == "confirmed",
        }
