# /qa-bug — Bug Capture → Ticket

Two modes:

- **Interactive** (default): tester reports one bug live. Capture via Chrome DevTools MCP, ask up to 4 sequential questions, confirm, file Jira ticket with screenshot.
- **Batch**: when `$REPORTS/run-analysis-*.md` or `.context/ui-test-bugs-draft.yml` exist — convert failures to tickets. Human confirms every ticket unless `[a]ll`.

Receives from orchestrator: `$REPORTS`, `$CASES`, `$GITHUB_REPO`, `$JIRA_URL`, `$JIRA_KEY`, `$MODELS`

## Config Guard

If `qa/qa-config.yml` not found:
```
qa/qa-config.yml not found.
Run /qa-init to scaffold (full setup) or /qa (auto-routes to init if missing).
```
Stop. Do not proceed.

## Step 0 — Mode Selection

Detect inputs:
- `recent_run_analysis` = newest `$REPORTS/run-analysis-*.md` mtime within last 24h
- `adversarial_draft` = `.context/ui-test-bugs-draft.yml` present

Routing:
- User invoked with a free-text description (e.g. `/qa-bug login button frozen`) → **Interactive** mode, seed initial summary from description.
- Neither input present, no description → **Interactive** mode.
- Either input present, no description → ask:
  ```
  Bug source:
    [i] interactive — capture a new bug now
    [b] batch      — file tickets from {N} parsed failures
  ```

Ask destination once (cached for session):
```
Create tickets in:
  [j] Jira   (project $JIRA_KEY)       — requires Atlassian MCP
  [g] GitHub (repo $GITHUB_REPO)       — requires gh auth
  [x] both
```

---

## Interactive Mode

### Step I.1 — Capture (parallel, silent)

In one batch, call Chrome DevTools MCP tools in parallel:
- `list_pages` — active tab URL, title
- `take_screenshot` — save to `qa/.context/bug-{ts}.png` (overwrite each run)
- `list_console_messages` — last 50, filter `error`/`warning`
- `list_network_requests` — last 50, filter status ≥ 400

If Chrome DevTools MCP unavailable: continue without capture, mark `evidence: none`.

**Redact before storing or sending anywhere:**
- HTTP headers: `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `X-Auth-Token` → `[REDACTED]`
- Request/response bodies: any field matching `password|token|secret|api[_-]?key|bearer` → `[REDACTED]`
- URL query params: `token|key|secret|password` → `[REDACTED]`

### Step I.2 — Sequential Questions (max 4)

Ask **one question at a time**. Wait for answer before next. Stop early if enough context.

Standard sequence (skip any already answered by initial description):
1. **What did you expect to happen?** (one sentence)
2. **What actually happened?** (one sentence — observed behavior)
3. **Reproduction steps?** (numbered or short prose)
4. **Severity?** `High` / `Medium` / `Low`

Never exceed 4 questions. If user is terse, infer the rest from capture + description.

### Step I.3 — Silent Analysis

In main context, derive:
- **Platform** — from `list_pages` URL (web app domain → `Web`; mobile schema → `Mobile`; else `Web`)
- **Domain** — single lowercase tag from URL path or description (e.g. `auth`, `checkout`, `profile`, `dashboard`). Match against existing TC domains in `$CASES` if any.
- **Severity → Priority** map: `High → High`, `Medium → Medium`, `Low → Low`
- **Build/OS** — from `list_pages` user-agent if available, else omit
- **Evidence bullets** (3–4): observations only from console errors, failed network calls, screenshot context. **No fixes. No confidence scores. No speculation as fact.** Each bullet is a thing seen, not a thing guessed.

### Step I.4 — Confirm Gate

Show preview:
```
Title:    [<Domain>] <one-liner>
Priority: <High|Medium|Low>
Labels:   <domain>

Description:
  <plain-language paragraph: what happened, when, where>

  **Expected:** <expected>

  **Steps to Reproduce:**
  1. ...
  2. ...

  **Additional Insight:**
  - <observation>
  - <observation>
  - <observation>

  **Environment:**
  - Platform: <Web|Mobile>
  - Build: <if known, else omit>
  - OS: <if known, else omit>
  - Domain: <domain>

Screenshot: qa/.context/bug-{ts}.png (will attach)

  [y] file ticket
  [e] edit field — title|description|priority|domain
  [c] cancel
```

Loop on `[e]` until `[y]` or `[c]`.

### Step I.5 — Create Ticket

**Jira** (`[j]` or `[x]`):
```
createJiraIssue(
  projectKey: $JIRA_KEY,
  issueType: "Bug",
  summary: "[<Domain>] <one-liner>",
  description: <markdown body from Step I.4>,
  priority: <High|Medium|Low>,
  labels: ["<domain>"]
)
```
Do **not** set sprint, fixVersion, components, or assignee. One label only.

If parent story key offered by user (optional question on `[e]`): after ticket created, call `createIssueLink(type: "Relates", inwardIssue: <new key>, outwardIssue: <parent>)`.

**Screenshot attachment:**
Read `JIRA_API_KEY` and `JIRA_EMAIL` from `qa/.env`. If both present:
```bash
curl -s -u "$JIRA_EMAIL:$JIRA_API_KEY" \
  -X POST \
  -H "X-Atlassian-Token: no-check" \
  -F "file=@qa/.context/bug-{ts}.png" \
  "$JIRA_URL/rest/api/3/issue/<new-key>/attachments"
```
If either missing: skip attachment silently. Never print key/email.

**GitHub** (`[g]` or `[x]`):
```bash
gh issue create \
  --repo $GITHUB_REPO \
  --title "[<Domain>] <one-liner>" \
  --label "bug,<domain>" \
  --body-file <(printf '%s' "$MARKDOWN_BODY")
```
Screenshot attachment via GH: include as image in body using uploaded URL only if user already has the image hosted; otherwise reference path.

### Step I.6 — Summary

```
Filed:
  Jira:   PROJ-123  (screenshot attached)
  GitHub: #42
```

Return to orchestrator: 1 filed.

---

## Batch Mode

### Step B.1 — Parse Failures (builder subagent)

Spawn builder with `$MODELS.default`.

**Input:** newest `run-analysis-*.md` + optional `.context/ui-test-bugs-draft.yml`.

**Output:** list of bug records, returned to main context (no disk writes):
```yaml
tc_id: "TC-WEB-1.2.3"      # if failure traces to a TC, else empty
domain: "auth"             # lowercase, single tag — from TC or inferred
title: ""                  # one-liner — max 80 chars, NO domain prefix (added later)
summary: ""                # plain-language paragraph
expected: ""               # from TC expected_result or adversarial assertion
actual: ""                 # observed
steps: []                  # imperative, numbered
priority: "Medium"         # High|Medium|Low — map from TC priority or infer
insight: []                # 3–4 observation bullets — no fixes
spec_path: ""              # failing spec file
log_excerpt: ""            # ≤20 lines
screenshot_path: ""        # if present in report
platform: "Web"            # Web|Mobile
```

**Quality rules:**
- Collapse duplicates (same spec + same assertion) into one record.
- Skip flaky-tagged failures unless user overrides.
- If multiple TCs share a root cause, list all in `summary`; first becomes `tc_id`.
- Strip any captured secrets from logs before returning (`Authorization`, `Cookie`, tokens, keys).

### Step B.2 — Confirm Gate

```
Found N bugs:
  1. [High]   [auth]     Password reset email not sent for SSO users
  2. [Medium] [checkout] Tax miscalculates for EU VAT
  3. [Low]    [legal]    Footer link to /legal returns 404
  [1..N]  inspect single
  [a]ll   file all
  [s]kip N,N
  [c]ancel
```

Inspect = full preview in Interactive Step I.4 format.

### Step B.3 — Create Tickets

Same call shape as Interactive Step I.5 — per record. Title becomes `[<Domain>] <title>`. Body uses Interactive Step I.4 format. Add `**TC:** <tc_id>` line above Expected if linked.

Screenshot attachment via curl as in Interactive mode, using each record's `screenshot_path` if present.

### Step B.4 — Backfill

For each bug with a `tc_id`:
- Append created issue key(s) to source `run-analysis-*.md` under a `## Filed Tickets` section.
- Do **not** modify TC YAML `jira_key` — that field is reserved for the TC's linked story, not the bug ticket.

If source was `.context/ui-test-bugs-draft.yml`: delete the draft after successful filing (adversarial completion signal).

### Step B.5 — Summary

```
Filed:
  Jira:   PROJ-123, PROJ-124, PROJ-125
  GitHub: #42, #43
Skipped: 1 flaky
```

---

## Rules

- Never create a ticket without user confirmation (single-item or `[a]ll`).
- Never transition existing tickets — creation only. Use `/qa-triage` for transitions.
- Never attach full logs — trim to ≤20 lines of signal.
- Never embed secrets, tokens, cookies, emails, or auth headers in issue bodies.
- Never fill sprint, fixVersion, components, or assignee.
- One label only: lowercase domain.
- **Additional Insight bullets are observations and evidence only — no suggested fixes, no confidence levels, no speculation as fact.**
- Max 4 questions in Interactive mode.
- All credentials (`JIRA_API_KEY`, `JIRA_EMAIL`, `GITHUB_TOKEN`) read from `qa/.env` — never hardcoded, never printed, never embedded in tickets.
- If MCP / gh auth / .env creds missing: print the markdown body for manual paste, do not stall the pipeline.
- Dedup by (spec_path + assertion_signature) within one run.
