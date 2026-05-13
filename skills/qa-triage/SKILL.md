---
name: qa-triage
description: Score in-flight Jira tickets against release signals via Atlassian MCP. Paste fallback if MCP unavailable. Ephemeral output.
---

# /qa-triage — Jira Ticket Triage

Receives from orchestrator: `$CASES`, `$GITHUB_REPO`, `$JIRA_URL`, `$JIRA_KEY`, `$JIRA_QA_STATUS`, `$MODELS`

## Config Guard

If `qa/qa-config.yml` not found:
```
qa/qa-config.yml not found.
Run /qa-init to scaffold (full setup) or /qa (auto-routes to init if missing).

Quick start — create qa/qa-config.yml:
  project:
    name: "My App"
  gen:
    playwright:
      enabled: true
      base_url: "http://localhost:3000"

Then re-run this skill.
```
Stop. Do not proceed.

## Step 0 — Setup

If `$JIRA_KEY` empty: ask `> Jira project key (e.g. PROJ):` — update `$JIRA_KEY`.
Verify Atlassian MCP: call `getAccessibleAtlassianResources`. If unavailable: ask user to paste ticket list (key + summary), skip to Step 3.

## Step 1 — Fetch Tickets

```
searchJiraIssuesUsingJql:
  jql: 'project = {JIRA_KEY} AND status in ("{JIRA_QA_STATUS}", "In QA") ORDER BY status ASC, priority ASC'
  fields: key, summary, description, priority, status
```

If none found: "No tickets in '{JIRA_QA_STATUS}' or 'In QA'." Stop.

## Step 2 — Fetch Release Signals

Ask: `> GitHub release URL (e.g. https://github.com/org/repo/releases/tag/v1.0.0):`

```bash
gh release view {TAG} --repo $GITHUB_REPO --json body,tagName,publishedAt
gh pr list --repo $GITHUB_REPO --state merged --limit 100 --json number,title,body,mergedAt,files
```

If `gh` fails: `WebFetch` on URL. If both fail: ask user to paste release notes.

## Step 3 — Score (subagent, model: `$MODELS.default`)

Spawn subagent with ticket list + signals corpus as inline text. If MCP tools are unavailable inside the subagent, the subagent uses only the inline text — no tool calls needed for scoring.

For each ticket:

**Signal** (highest that applies):
- `confirmed` — ticket key verbatim in PR title/body or release notes
- `likely` — 3+ title keywords match PR title or release notes
- `possible` — 1–2 weak matches
- `none` — no match

**Complexity:**
- `low` — UI-only, no sync/offline/multi-step
- `complex` — offline, sync, conflict, data migrations, multi-step wizard
- `medium` — everything else

Return YAML list per ticket: key, signal, matched_prs, complexity.

## Step 4 — TC Coverage Check

Grep `$CASES/` for each ticket's Jira key. Record `has_tcs: true/false`, `tc_ids: [...]`.

## Step 5 — Output

```
QA Triage — {DATE}
{N} tickets  |  Release: {TAG}  |  {N} PRs scanned
──────────────────────────────────────────────────

TIER 1 — Test Now ({N} — confirmed/likely)
  1. {KEY}  {Summary}  [{status}]
     Signal: {match_reason}  Complexity: {complexity}
     TCs: {ids or "none"}
  ...

TIER 2 — Verify First ({N} — partial signal)
  ...

TIER 3 — Skip ({N} — no signal)
  ...

──────────────────────────────────────────────────
[w] walkthrough  [r] report (walkthrough + transition)  [p] pipeline handoff  [q] quit
```

## Step 6 — Pipeline Handoff

Show:
```
No TCs ({N}): {KEY list} → /qa-plan
Has TCs, not automated ({N}): {KEY list} → /qa-codegen
```

`Run /qa-plan for uncovered? [y/n]`
`Run /qa-codegen for automation candidates? [y/n]`

If yes: invoke relevant skill scoped to that ticket list.

## Step 7 — Walkthrough (if chosen)

For each Tier 1 ticket in order:
```
── {KEY}: {Summary} ──
Priority: {p}  Linked PRs: #{n}
TCs: {ids or "none"}
{Jira description / acceptance criteria}
Testing focus: {1–3 bullets}
──────────────────────
Result: [pass / fail / skip / block]
```

On `fail`/`block`: offer Jira comment via `addCommentToJiraIssue`. Confirm before sending.

Plain walkthrough mode (`[w]`) never transitions — comment-only.

## Step 7b — Report Mode (`[r]`)

Opt-in bidirectional flow. Walkthrough as in Step 7, plus per-ticket transition prompt.

**Before first transition**, fetch available transitions once per ticket status:
```
getTransitionsForJiraIssue(issueIdOrKey: {KEY})
```

Build status → transition-id map cached in session. Show user the resolved target before firing.

**Result mapping (configurable defaults):**

| Result | Transition target (default) | Comment appended |
|--------|-----------------------------|------------------|
| pass   | `Passed` / `Done` / `Closed` (first match from transition list) | `QA pass — run {DATE} — TCs: {ids}` |
| fail   | `Failed` / `Reopened` / `In Progress` | failure summary + TC ids |
| block  | `Blocked` / `On Hold` | blocker reason (required) |
| skip   | no transition | `QA skipped — {reason}` if reason provided |

If no matching transition name exists on the ticket's workflow: show list, ask user to pick id, skip if they decline.

**Per-transition gate (mandatory — never skip):**
```
{KEY}: pass → transition "Done" (id: 31)
Comment: "QA pass — run 2026-04-22 — TCs: TC-WEB-1.1.1, TC-WEB-1.1.2"
[y] transition + comment
[c] comment only (no transition)
[n] skip
[e] edit comment
```

On `y`:
```
transitionJiraIssue(issueIdOrKey: {KEY}, transition: { id: {id} })
addCommentToJiraIssue(issueIdOrKey: {KEY}, commentBody: {body})
```

**Batch mode (`[a]ll after first`):**
After first confirmed transition of a given `result` → offer `Apply same rule to remaining {result} results? [y/n]`. On `y`: auto-fire matching target + templated comment for subsequent tickets without per-item prompt. User can still abort with Ctrl+C; each transition logged to terminal as it fires.

Batch mode expires at end of triage run — never persisted.

## Rules

- Plain walkthrough (`[w]`) never transitions — comments only.
- Report mode (`[r]`) requires explicit per-item confirmation for first transition per result class; batch auto-fire only after explicit `[a]ll` opt-in.
- Never auto-transition on MCP failure — print the intended transition as plain text so user can apply manually.
- Never invent pass/fail — only what user explicitly reports.
- Complexity is advisory — label `[estimated]`.
- If Atlassian MCP unavailable: accept pasted list, skip Steps 1, 7, 7b.
- No report files written — triage is ephemeral. Transition history lives in Jira itself.
