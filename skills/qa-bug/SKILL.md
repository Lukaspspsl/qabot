---
name: qa-bug
description: Create one bug ticket from live evidence (browser capture + tester description) or batch-file failures from a qa-run report. Config-driven — no hardcoded project or company details. Replaces the standalone /bug skill.
---

# /qa-bug — Bug Ticket Creation

Two modes, detected automatically:

- **Live mode** — invoked directly (`/qa-bug` or `/qa-bug <description>`) or from `/qa-live` with pre-filled context. Captures browser state, asks tester, files one ticket.
- **Batch mode** — invoked by `/qa` orchestrator after `/qa-run`. Parses `run-analysis-*.md`, files multiple tickets with `[a]ll` / selective confirm.

---

## Config Guard

Read `qa/qa-config.yml`. If missing → stop:
```
qa/qa-config.yml not found. Run /qa-init first.
```

Resolve config values:
- `$JIRA_URL` = `project.jira.url`
- `$JIRA_KEY` = `project.jira.project_key`
- `$JIRA_CLOUD_ID` = `project.jira.cloud_id`  ← new field (see Config section)
- `$GITHUB_REPO` = `project.github_repo`
- `$MODELS` = `models.*`
- `$REPORTS` = `paths.reports`
- `$CASES` = `paths.cases`

Screenshot upload requires `JIRA_API_KEY` in `qa/.env`. Read it there — never from config.

---

## Mode Detection

**Live mode** when ANY of:
- Invoked directly with no prior run-analysis context
- Args contain a description string (`/qa-bug login button returns 500`)
- Called from `/qa-live` with pre-filled YAML context block

**Batch mode** when:
- Invoked by `/qa` orchestrator with `$REPORTS` set and a `run-analysis-*.md` exists
- Invoked standalone with no description and a `run-analysis-*.md` exists

---

## LIVE MODE

### Step L0 — Pre-filled Context (from /qa-live)

If `/qa-live` injected a context block, extract:
```yaml
source: qa-live
tc_id: ""
title: ""
steps_to_reproduce: ""
expected: ""
actual: ""
severity: ""          # P1|P2|P3|P4
evidence:
  log_excerpt: ""
  console_snapshot: ""
  screenshot_path: ""
```

Skip questions already answered by pre-filled fields (do not re-ask).

### Step L1 — Browser Capture (silent, parallel)

Call `list_pages` via Chrome DevTools MCP. If no tab found or MCP unavailable — skip silently, continue.

If tab found, capture in parallel:
- `take_screenshot` (viewport only) → save to `$REPORTS/<slug>-<timestamp>-screenshot.png`
- `list_console_messages` types `["error","warn"]`
- `list_network_requests` resourceTypes `["xhr","fetch","document","other"]` — flag 4xx/5xx and no-response
- `evaluate_script` → `({ url: location.href, title: document.title })`

For each failed/suspicious request (max 5): call `get_network_request`, extract method, URL, status, request/response headers, response body (first 500 chars).

**Always redact** `Authorization`, `Cookie`, `Set-Cookie` header values → `[REDACTED]`.

### Step L2 — Ask Tester

Skip any question already answered by pre-filled context or initial description.

Ask only what's missing (max 4 questions total, one at a time):

0. **Actual result** — if description missing or unclear: "What happened?"
1. **Steps to reproduce** — if not pre-filled
2. **Expected result** — if not pre-filled
3. **Severity**: `[1] P1 — Critical  [2] P2 — High  [3] P3 — Medium  [4] P4 — Low`
4. **Linked references** (optional): "TC ID and/or Jira story key — e.g. `TC-WEB-1.2.3 PROJ-45` — Enter to skip"
   - Parse: `TC-\w+-\d+\.\d+\.\d+` pattern → `related_tc`; `[A-Z]+-\d+` (non-TC) → `parent_story`

### Step L3 — Analysis (silent)

Cross-reference: console errors, failed requests, headers, payloads, URL state, pre-filled evidence, tester description.

Determine:
- **Platform**: `iOS` / `Android` / `mobile` / `web` / `backend`
- **Domain**: most specific functional area (screen / feature / module). Use "General" only if no clear domain.

Produce 3–4 evidence bullets: specific log lines, request URLs, error codes, component names. No fixes. No speculation.

Derive severity from TC priority if `related_tc` found and severity not explicitly given:
- `critical` → P1, `high` → P2, `medium` → P3, `low` → P4

### Step L4 — Confirm Gate

Show preview:
```
Title:     [{Domain}] {one-liner}
Severity:  {P1|P2|P3|P4}
Platform:  {platform}
Label:     {domain-lowercase}
TC:        {related_tc or —}
Linked:    {parent_story or —}
Screenshot:{filename or —}
Dest:      {Jira $JIRA_KEY / GitHub $GITHUB_REPO / both}
```

Ask destination if not already known:
```
Create in: [j] Jira  [g] GitHub  [b] both
```

Prompt: `[y] create  /  [n] cancel  /  [e] edit field`

Only proceed on `y`.

### Step L5 — Create Ticket

#### Jira

Call `mcp__claude_ai_Atlassian__createJiraIssue`:
- `cloudId`: `$JIRA_CLOUD_ID`
- `projectKey`: `$JIRA_KEY`
- `issueType`: `"Bug"`
- `summary`: `[{Domain}] {one-liner title, max 80 chars}`
- `contentFormat`: `"markdown"`
- `description`:

```markdown
{2–4 sentences. What is broken, its implication, probable cause. Plain language.}

**Expected:** {one-liner}

### Steps to Reproduce
1. {prerequisite / navigation}
2. {action}
3. {action}

### Evidence
- {specific log line, error code, or request}
- {observation}
- {observation}
- {4th only if needed}

### Environment
**Platform:** {platform} | **Domain:** {domain}
{**TC:** {related_tc} | } {**Report:** {report_path if batch} | }
```

- `additional_fields`: `{"priority": {"name": "{Critical|High|Medium|Low}"}, "labels": ["{domain-lowercase}"]}`

  Severity → Jira priority: P1 → `Critical`, P2 → `High`, P3 → `Medium`, P4 → `Low`

If `parent_story` set: call `mcp__claude_ai_Atlassian__createIssueLink`:
- `type`: `"Relates"`
- `inwardIssue`: new bug key
- `outwardIssue`: parent_story

**Screenshot attachment** (if captured):
```bash
source qa/.env && curl -s \
  -u "${JIRA_USER}:${JIRA_API_KEY}" \
  -H "X-Atlassian-Token: no-check" \
  -F "file=@{screenshot_path}" \
  "{$JIRA_URL}/rest/api/3/issue/{KEY}/attachments"
```
- `JIRA_USER` and `JIRA_API_KEY` from `qa/.env` — skip upload silently if missing, note in output
- Never embed screenshot inline in description

If Jira MCP unavailable: print ready-to-paste markdown body, continue.

#### GitHub

```bash
gh issue create \
  --repo "$GITHUB_REPO" \
  --title "[QA] [{Domain}] {one-liner}" \
  --label "bug,qa-manual" \
  --body-file <(printf '%s' "$MARKDOWN_BODY")
```

If `gh` unavailable: print markdown body, continue.

### Step L6 — Output

```
Ticket: {KEY} {url}
Severity: {P1|P2|P3|P4}  |  Label: {domain}  |  Linked: {parent_story or —}  |  Screenshot: {filename or —}
```

Stop.

---

## BATCH MODE

Receives from orchestrator: `$REPORTS`, `$CASES`, `$GITHUB_REPO`, `$JIRA_URL`, `$JIRA_KEY`, `$JIRA_CLOUD_ID`, `$MODELS`

### Step B0 — Source Selection

Scan:
- Latest `$REPORTS/run-analysis-*.md` (by mtime)
- `$REPORTS/.context/ui-test-bugs-draft.yml` (if present — from `/qa-adversarial`)

If neither exists: stop with `No failures to report. Run /qa-run or /qa-adversarial first.`

Ask destination:
```
Create tickets in:
  [j] Jira   ($JIRA_KEY)      — requires Atlassian MCP
  [g] GitHub ($GITHUB_REPO)   — requires gh auth
  [b] both
```

### Step B1 — Parse Failures

Spawn builder subagent (`$MODELS.default`).

**Input:** run-analysis markdown + optional adversarial draft YAML.
**Output:** structured list of bug records (never write to disk — return to main context).

Record shape:
```yaml
tc_id: ""               # TC ID if traceable, else empty
title: ""               # max 80 chars, action-oriented
summary: ""             # one paragraph
steps_to_reproduce: []
actual: ""
expected: ""
severity: "P2"          # P1|P2|P3|P4 — inherit from TC priority if linked, else infer
evidence:
  log_excerpt: ""       # ≤20 lines
  screenshot_path: ""   # if present in report
  spec_path: ""
labels: ["qa-auto"]
```

Quality rules:
- Collapse duplicates (same spec + same assertion) → one record
- Flaky-tagged failures → skip unless user overrides
- Multiple TCs with same root cause → reference all in `summary`, first as `tc_id`

### Step B2 — Confirm Gate

```
Found N bugs:
  1. [P1] TC-WEB-1.2.3 — {title}
  2. [P2] TC-WEB-2.1.1 — {title}
  3. [P3] (no TC)      — {title}
  4. [P4] TC-WEB-3.1.2 — {title}

[1..N] inspect single  [a]ll create all  [s]kip N,N  [c]ancel
```

### Step B3 — Create Tickets

For each confirmed record — same Jira + GitHub creation as Step L5, using record fields. No screenshot upload (no browser session in batch mode).

### Step B4 — Backfill

For each filed bug with `tc_id`:
- Append issue key(s) to `$REPORTS/run-analysis-<timestamp>.md` under `## Filed Tickets`
- Do **not** modify TC YAML `jira_key`

If source was adversarial draft YAML: delete after successful filing.

### Step B5 — Summary

```
Filed:
  Jira:   {keys}
  GitHub: {numbers}
Skipped: {N} flaky
```

Return to orchestrator: filed count per destination.

---

## Config Addition Required

Add to `qa-config.yml` template under `project.jira`:

```yaml
project:
  jira:
    url: ""           # https://myorg.atlassian.net
    project_key: ""   # PROJ
    cloud_id: ""      # Atlassian cloud ID — find at: $JIRA_URL/_edge/tenant_info
    ready_for_qa_status: "Ready for QA"
```

Add to `qa/.env.example`:
```
# Jira (required for screenshot attachment via REST API)
JIRA_USER=""        # your Atlassian email
JIRA_API_KEY=""     # Atlassian API token — https://id.atlassian.com/manage-profile/security/api-tokens
```

---

## Rules

- Never create ticket without user confirmation (live: Step L4; batch: Step B2).
- Never transition existing tickets — creation only. Use `/qa-triage` for transitions.
- Never attach full logs — trim to ≤20 lines. Link to report path instead.
- Never embed secrets from `.env` in ticket bodies.
- Never hardcode project key, cloud ID, user email, or company domain.
- Screenshot: always save as file, never base64 inline in description.
- Inspect at most 5 requests in detail (live mode).
- Redact `Authorization`, `Cookie`, `Set-Cookie` always.
- If MCP / `gh` unavailable: print markdown body, do not stall.
- Dedup within one batch run by `(spec_path + assertion_signature)`; across runs, user manages.
- One label only in live mode (domain-lowercase); batch mode adds `qa-auto` source tag.
