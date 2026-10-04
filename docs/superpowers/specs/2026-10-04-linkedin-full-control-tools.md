# LinkedIn MCP — Full Control Tools (2026-10-04)

## Goal

Extend the existing LinkedIn MCP server with typed write/action tools so it
covers posting, engagement, connections, job actions, follow control,
notifications, and settings — beyond today's mostly read-only surface.

## Existing context

- FastMCP server; tools registered via `register_*_tools(mcp, tool_timeout=...)`
  in `linkedin_mcp_server/tools/`, wired centrally in `server.py`.
- Page interaction helpers live in `linkedin_mcp_server/linkedin/`
  (e.g. `posts.py`, `connection_actions.py`, `message_sender.py`, `content.py`).
- Tool modules follow: `get_ready_extractor(ctx, tool_name=...)`,
  `extractor.extract_page(url, section)`, `extractor.page.evaluate(js, ...)`,
  `ctx.report_progress`, `raise_tool_error`, `AuthenticationError` handling.
- Tests: pytest, mocked `page.evaluate` / extractor.

## New tool surface

| Area (module) | Tools |
|---|---|
| `tools/posts_actions.py` | `create_post`, `delete_post`, `create_post_with_image` |
| `tools/engagement.py` | `react_to_post`, `comment_on_post`, `reply_to_comment`, `get_post_reactions` |
| `tools/connections.py` | `list_pending_invitations`, `accept_invitation`, `decline_invitation`, `withdraw_connection_request` |
| `tools/job_actions.py` | `save_job`, `unsave_job`, `apply_to_job` |
| `tools/follow.py` | `follow_person`, `unfollow_person`, `follow_company`, `unfollow_company` |
| `tools/notifications.py` | `get_notifications`, `mark_notifications_read` |
| `tools/settings.py` | `list_settings_sections`, `get_setting`, `update_setting` |

Each write tool accepts `dry_run: bool = False`. With `dry_run=True` the tool
navigates/prepares and reports the intended action without clicking submit.
All write tools carry `destructiveHint` where appropriate and explicit
input/output schemas, bounded timeouts, actionable errors.

## Approach

Follow the existing FastMCP registration pattern (one `register_*_tools` per
area + `linkedin/<area>.py` JS-evaluate helpers). No DccServerBase skill
package, no raw script execution as primary workflow.

## Testing / validation

- Unit tests per area with mocked extractor/page (pytest, mocked
  `page.evaluate`), invalid input and "control not found" paths.
- `ruff` lint + full `pytest` green.
- Live validation: read tools live; write tools via `dry_run=True` first;
  real mutation only on explicit user confirmation. Mock/dry-run is the
  default validation path.

## Out of scope

- Account credential management, bypassing LinkedIn rate limits, scraping
  beyond what normal UI automation exposes.
- DCC/FastMCP migration — server stays on its current runtime.

## Risks

- LinkedIn DOM churn → selectors centralized per area module, single update
  point; failures return structured actionable errors.
- Real-account side effects → `dry_run` everywhere + confirm-gated usage.
