---
name: qa-live
description: Interactive manual testing buddy. Walks TCs one at a time, enriches each with LLM tip + 2 questions, captures verdicts + observations, hands off to /qa-bug on failure. Fully standalone — no dependency on prior /qa phases.
---

# /qa-live — Manual Testing Session

## Prerequisites

Read `qa/qa-config.yml`. If missing → stop: "Run `/qa-init` first."

Config values used:
- `$CASES` = `paths.cases` (default: `qa/cases`)
- `$REPORTS` = `paths.reports` (default: `qa/reports`)
- `$MODELS.default` = `models.default`
- `$JIRA_URL` = `project.jira.url`
- `$JIRA_KEY` = `project.jira.project_key`
- `$LIVE_BURP` = `live_session.tools.burp.enabled`
- `$LIVE_DEVTOOLS` = `live_session.tools.devtools.enabled`
- `$LIVE_JIRA_COMMENTS` = `live_session.tools.jira.comment_on_verdict`

## Step 0 — TC Resolution

Parse args. Three modes:

**Feature name** (`/qa-live auth`):
- Glob `$CASES/auth/**/*.yml` (or any subdirectory matching the feature name)
- Error if zero TCs found

**TC IDs** (`/qa-live TC-WEB-1.1.1,TC-WEB-1.1.2`):
- Load each by scanning `$CASES/**/*.yml` for matching `id:` fields
- Error if any ID not found

**Sprint/label filter** (`/qa-live --sprint "Sprint 12"` or `--label regression`):
- Requires `project.jira` configured — error if `$JIRA_URL` or `$JIRA_KEY` empty
- Fetch TCs from Jira: search issues via `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql` where sprint or label matches
- Extract `jira_key` values, then load matching TCs from `$CASES` by `jira_key` field
- Error if Jira MCP unavailable: "Jira not configured — use feature name or TC IDs instead"

**No args** → error: "Usage: `/qa-live <feature>` or `/qa-live TC-WEB-1.1.1,…` or `/qa-live --sprint <label>`"

**Sort** loaded TCs by priority: `critical` → `high` → `medium` → `low` (stable within each tier — preserve file order among same-priority TCs).

Generate session timestamp: `YYYYMMDD-HHMMSS` (used for report filename).

Show:
```
── /qa-live session started ─────────────────────────────
Scope:    {feature / TC IDs / sprint label}
TCs:      {N} loaded ({critical count} critical, {high} high, {medium} medium, {low} low)
Controls: [P]ass  [F]ail  [S]kip  [E]nd session
─────────────────────────────────────────────────────────
```

Initialize session log in memory:
```
results: []   # { tc_id, title, priority, verdict, notes, bug_key }
```

## Step 1 — Per-TC Loop

For each TC (in sorted order):

### 1a. Display TC

```
━━ {index}/{total} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tc.id}  [{tc.priority}]  {tc.title}

Preconditions:
{tc.preconditions joined as bullet list, or "—" if empty}

Steps:
{tc.steps}

Expected result:
{tc.expected_result}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 1b. Fetch Jira context (conditional)

If `tc.jira_key` is non-empty AND `$JIRA_URL` is configured:
- Call `mcp__claude_ai_Atlassian__getJiraIssue` with the jira_key
- Show: `Jira: {key} — {ticket summary}` (one line)
- If MCP call fails or MCP unavailable: skip silently, continue

### 1c. Generate buddy block

Spawn a lightweight subagent (model: `$MODELS.default`).

Subagent prompt:
```
You are a senior QA engineer reviewing a test case before manual execution.

Output exactly three lines — no preamble, no headers, no explanation:
Tip: {one sentence — the single most important risk, edge case, or fragility a tester should watch for}
Q1: {a challenging question the tester should be able to answer after executing this TC}
Q2: {a second, different challenging question}

Rules:
- Tip: max 15 words. Specific to this TC, not generic advice.
- Questions: should require the tester to observe something non-obvious. Not yes/no.
- If the TC is trivial and you have nothing useful to say, still output all three lines but keep them brief.

Test case:
{tc_yaml_content}

App context:
{QA_CONTEXT.md content, or "No QA context available." if file missing}
```

Display subagent output verbatim:
```
> Tip: {tip}
> Q1:  {question 1}
> Q2:  {question 2}
```

### 1d. Await verdict

Prompt tester:
```
Verdict [P/F/S/E] or type observations then verdict:
```

Accept any of these as the first token (case-insensitive): `p`, `pass`, `f`, `fail`, `s`, `skip`, `e`, `end`

Tester may type inline observations before the verdict letter (e.g. `F — 500 on submit, console shows CORS error`). Parse: everything before the verdict letter = observations.

**Special keywords** (tester types these instead of a verdict):
- `check burp` — if `$LIVE_BURP` enabled: fetch recent Burp proxy history via configured Burp MCP server and display relevant requests for this TC's expected flow. Then re-prompt for verdict. If Burp not configured: "Burp not enabled — set `live_session.tools.burp.enabled: true` in qa-config.yml."
- `check devtools` or `check console` — if `$LIVE_DEVTOOLS` enabled: call `mcp__io_github_ChromeDevTools_chrome-devtools-mcp__list_console_messages` and `mcp__io_github_ChromeDevTools_chrome-devtools-mcp__list_network_requests`, display output. Re-prompt for verdict. If not configured: "DevTools not enabled."
- Pasted log block (multi-line, no verdict) — buddy parses for error patterns (4xx/5xx, stack traces, `Error:`, `Warning:`), highlights anomalies inline, notes them in session log. Re-prompts for verdict.

### 1e. Handle PASS

- Append to session log: `{ tc_id, title, priority, verdict: PASS, notes: {observations or ""} }`
- If `$LIVE_JIRA_COMMENTS` is true AND `tc.jira_key` non-empty AND Jira MCP available:
  - Call `mcp__claude_ai_Atlassian__addCommentToJiraIssue`
  - Body: `✅ PASS — qa-live session {timestamp} on {date}. {observations if any}`
  - Fail silently if MCP call fails.
- Continue to next TC.

### 1f. Handle FAIL

Append to session log: `{ tc_id, title, priority, verdict: FAIL, notes: {observations or ""} }`

If `$LIVE_JIRA_COMMENTS` is true AND `tc.jira_key` non-empty AND Jira MCP available:
- Call `mcp__claude_ai_Atlassian__addCommentToJiraIssue`
- Body: `❌ FAIL — qa-live session {timestamp}. {one-line summary of observations}`
- Fail silently if MCP call fails.

Ask tester:
```
File bug now or log and continue?
[B]ug — invoke /qa-bug with pre-filled context
[C]ontinue — log failure, file bugs at end of session
```

**If B (bug now):**
- If tester hasn't provided observations yet, ask: "Describe what actually happened:"
- If `$LIVE_DEVTOOLS` enabled: capture `list_console_messages` + `list_network_requests` and include as evidence
- Invoke `/qa-bug` with the following context injected into its prompt:

  ```
  Source: qa-live
  TC ID: {tc.id}
  Title: {tc.title}
  Steps to reproduce: {tc.steps}
  Expected: {tc.expected_result}
  Actual: {tester observations}
  Severity: {critical→P1, high→P2, medium→P3, low→P4}
  Evidence:
    log_excerpt: {pasted log if any, trimmed to 20 lines}
    console_snapshot: {DevTools output if captured, else empty}
  ```

  `/qa-bug` handles Jira creation and its own user confirmation gate — do not duplicate.

- After `/qa-bug` returns: extract filed bug key, update session log entry: `bug_key: {key}`
- Continue to next TC.

**If C (continue):**
- Mark session log entry `bug_key: pending`
- Continue to next TC.

### 1g. Handle SKIP

- Append to session log: `{ tc_id, title, priority, verdict: SKIP, notes: "N/A" }`
- No Jira comment.
- Continue to next TC.

### 1h. Handle END

- Break loop immediately.
- Note in session log that session ended early at `{tc_id}` (index `{n}` of `{total}`).
- Proceed to Step 2.

---

## Step 2 — Session Report

Write `$REPORTS/live-session-{timestamp}.md`:

```markdown
# Live Session Report — {date}

**Session:** {timestamp}
**Scope:** {feature / TC IDs / sprint label}
**Tester:** {project.name or "unknown"}
**TCs completed:** {completed} of {total}

## Summary

| Total | Pass | Fail | Skip | Not run |
|-------|------|------|------|---------|
| {total} | {pass_count} | {fail_count} | {skip_count} | {not_run} |

## Results

| TC ID | Title | Priority | Verdict | Notes |
|-------|-------|----------|---------|-------|
{one row per completed TC}

## Bugs Filed

| TC ID | Bug Key | Title |
|-------|---------|-------|
{one row per TC with bug_key set and not "pending"}

## Pending Failures (not yet filed)

| TC ID | Title | Observations |
|-------|-------|-------------|
{one row per TC with bug_key: pending}
```

After writing: tell tester where the report was saved.

If **Pending Failures** table is non-empty, ask:
```
File bugs for {N} pending failure(s) now? [Y/N]
```
- **Y**: invoke `/qa-bug` with the batch of pending failures as context (same format as 1f)
- **N**: session done. Remind tester: "Pending failures logged in report — run `/qa-bug` manually when ready."

Show final summary:
```
── Session complete ──────────────────────────────────────
Pass: {N}  Fail: {N}  Skip: {N}  Not run: {N}
Report: $REPORTS/live-session-{timestamp}.md
─────────────────────────────────────────────────────────
```

---

## Rules

- Never modify TC YAML files — read-only during a live session.
- Never auto-file bugs without the tester's explicit `[B]ug` or `[Y]` response.
- Never auto-transition Jira tickets (creation-only, same as `/qa-bug`).
- Never re-read `qa-config.yml` mid-session — all config resolved at Step 0.
- All MCP integrations are optional. Skill must run fully without any MCP configured.
- Buddy subagent spawned per TC — lightweight, no doc injection, no file reads beyond TC + QA_CONTEXT.
- Jira comments fail silently — never block progression on MCP errors.
- Tester controls pace entirely. Never auto-advance.
