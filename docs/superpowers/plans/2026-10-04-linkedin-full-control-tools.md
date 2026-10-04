# LinkedIn Full-Control Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add typed write/action MCP tools (posting, engagement, connections, job actions, follow, notifications, settings) to the existing LinkedIn MCP server.

**Architecture:** Each area is a thin tool module under `linkedin_mcp_server/tools/` following the exact `update.py` pattern (inline JS evaluate steps, `get_ready_extractor`, progress reporting, `raise_tool_error`). Registered centrally in `server.py`. Write tools take `dry_run`.

**Tech Stack:** Python 3.13, FastMCP, Patchright, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-04-linkedin-full-control-tools.md`

**Pattern reference:** `linkedin_mcp_server/tools/update.py` and `tests/test_update_tools.py` — copy these shapes for every new module.

**Global constraints:** `dry_run: bool = False` on every write tool; `destructiveHint` annotations on mutating tools, `readOnlyHint` on readers; no label-value dependence in selectors (attribute/ARIA/URL/structural per AGENTS.md page rules); errors via `raise_tool_error`; `AuthenticationError` path like `update.py`; timeouts via `DEFAULT_TOOL_TIMEOUT_SECONDS`.

---

### Task 1: tools/posts_actions.py — create_post, delete_post, create_post_with_image

**Files:** Create `linkedin_mcp_server/tools/posts_actions.py`, `tests/test_posts_actions_tools.py`; Modify `linkedin_mcp_server/server.py` (import + register call).

- `[ ]` Write failing tests mirroring `test_update_tools.py`: success path with mocked evaluate sequence, `not_found` dialog path, `dry_run=True` short-circuit (no submit click sequence), and invalid URL.
- [ ] Implement `register_posts_actions_tools(mcp, tool_timeout=DEFAULT_TOOL_TIMEOUT_SECONDS)` with tools:
  - `create_post(text: str, ctx: Context, dry_run: bool = False) -> dict` — navigate `/feed/`, JS opens composer (`Start a post` control by aria-haspopup/role), sets text into contenteditable, clicks `Post` unless dry_run; verify via dialog close/toast status string.
  - `delete_post(post_urn_or_url: str, ctx: Context, dry_run: bool = False) -> dict` — navigate to post URL, open per-post menu (button aria-haspopup within post container), click Delete, confirm dialog Delete unless dry_run.
  - `create_post_with_image(text, image_path, ctx, dry_run=False) -> dict` — open composer, set text, attach file via `page.set_input_files` on file input, click Post unless dry_run.
- [ ] Wire into `server.py` next to `register_update_tools`.
- [ ] Run: `pytest tests/test_posts_actions_tools.py -v` → PASS; `ruff check linkedin_mcp_server/tools/posts_actions.py`.
- [ ] Commit.

### Task 2: tools/engagement.py — react_to_post, comment_on_post, reply_to_comment, get_post_reactions

Same pattern. Navigation to post URL; react = click Like/reaction button then optional reaction type in reaction bar; comment = focus comment composer, fill, click Post; reply = click reply control under Nth comment (index param), fill, click Reply; get_post_reactions = read counts + top reaction labels from the social counts row. Tests: success, composer missing, dry_run.

### Task 3: tools/connections.py — list_pending_invitations, accept_invitation, decline_invitation, withdraw_connection_request

Navigate `https://www.linkedin.com/mynetwork/invitation-manager/`. Read invitation rows (name, headline, urn/id, direction). accept/decline click the row's accept/ignore button by index or name match; withdraw navigates to Mine tab / pending sent list and clicks Withdraw then confirm. Tests: list extraction, accept by name, accept by index, missing row, dry_run.

### Task 4: tools/job_actions.py — save_job, unsave_job, apply_to_job

Navigate job URL `https://www.linkedin.com/jobs/view/<id>/`; save = click Save button toggle (aria-pressed flip), verify aria-pressed; unsave flips back; apply_to_job clicks Easy Apply control, returns status `opened`/`external`/`unavailable` and stops after first step unless caller wants full submission (v1: returns the application dialog state; dry_run returns `opened_dry_run`). Tests per outcome.

### Task 5: tools/follow.py — follow_person, unfollow_person, follow_company, unfollow_company

Profile/company page; find Follow/Following button by aria-pressed/presence, toggle; verify state flip; unfollow equivalents. Tests: follow success, already-following no-op, unfollow missing control.

### Task 6: tools/notifications.py — get_notifications, mark_notifications_read

Navigate `https://www.linkedin.com/notifications/`; read list entries (text, time, unread dot presence per row); mark read = click settings/mark-all-read or per-row menu. Tests: extraction, mark-all-read clicked, dry_run.

### Task 7: tools/settings.py — list_settings_sections, get_setting, update_setting

Navigate `https://www.linkedin.com/settings/`; list section links; get_setting navigates section and reads rows (label + current value); update_setting finds the row by its setting name and toggles/flips the control, verifying value flip; bounded to settings pages. Tests: list, get single, update toggle success, row missing, dry_run.

### Task 8: Full verification

- [ ] `pytest -q` (full suite) green
- [ ] `ruff check` + `ruff format --check` on new files
- [ ] Restart/reload note for MCP client (server reload) — report to user
