# /qa-bug — Failure → Ticket

Turns `qa/reports/run-analysis-*.md` failures (and optional `.context/ui-test-bugs-draft.yml` adversarial findings) into Jira issues or GitHub issues. Human confirms every ticket unless `[a]ll` batch mode selected.

Receives from orchestrator: `$REPORTS`, `$CASES`, `$GITHUB_REPO`, `$JIRA_URL`, `$JIRA_KEY`, `$MODELS`

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

## Step 0 — Source Selection

Scan inputs:
- Latest `$REPORTS/run-analysis-*.md` (by mtime)
- `.context/ui-test-bugs-draft.yml` (if present — from `/qa-adversarial`)

If neither exists: stop with `No failures to report. Run /qa-run or /qa-adversarial first.`

Ask destination:
```
Create tickets in:
  [j] Jira   (project $JIRA_KEY)       — requires Atlassian MCP
  [g] GitHub (repo $GITHUB_REPO)       — requires gh auth
  [b] both
```

## Step 1 — Parse Failures (Builder)

Spawn builder subagent with `$MODELS.default`.

**Input:** run-analysis markdown + optional adversarial draft YAML.

**Output:** list of bug records, one per failure. Never write to disk — return structured list to main context.

Record shape:
```yaml
tc_id: "TC-WEB-1.2.3"          # if failure traces to an existing TC, else empty
title: ""                       # concise, action-oriented — max 80 chars
summary: ""                     # one paragraph — what broke, what was expected
steps_to_reproduce: []          # imperative
actual: ""                      # observed
expected: ""                    # from TC expected_result or adversarial assertion
severity: "P2"                  # P1|P2|P3 — inherit from TC priority if linked, else infer
evidence:
  log_excerpt: ""               # trimmed stack / error lines (≤20 lines)
  screenshot_path: ""           # if present in report
  spec_path: ""                 # failing spec file
labels: ["qa-auto", "web"]      # platform tag + source tag (qa-run|qa-adversarial)
```

**Quality rules:**
- Collapse duplicate failures (same spec + same assertion) into one record.
- Flaky-tagged failures (from `/qa-run` analysis) → skip unless user overrides.
- If multiple TCs fail for the same root cause, reference them all in `summary`; pick the first as `tc_id`.

## Step 2 — Confirm Gate (Validator pattern)

Show compact list:
```
Found N bugs:
  1. [P1] TC-WEB-1.2.3 — Checkout total miscalculates tax for EU VAT
  2. [P2] TC-WEB-2.1.1 — Password reset email not sent for SSO users
  3. [P3] (no TC)      — Footer link to /legal returns 404
Confirm:
  [1..N]  inspect single
  [a]ll   create all
  [s]kip N,N  exclude by number
  [c]ancel
```

Inspect shows full record. Confirmation creates tickets.

## Step 3 — Create Tickets

### Jira (`[j]` or `[b]`)

For each confirmed record:
```
createJiraIssue(
  projectKey: $JIRA_KEY,
  issueType: "Bug",
  summary: title,
  description: """
    {summary}

    **TC:** {tc_id or "—"}
    **Severity:** {severity}

    **Steps to reproduce:**
    {numbered steps}

    **Expected:** {expected}
    **Actual:** {actual}

    **Spec:** {spec_path}
    **Log:**
    ```
    {log_excerpt}
    ```
    """,
  labels: labels
)
```

Capture returned issue key. If MCP unavailable: print ready-to-paste markdown block, continue to GitHub.

### GitHub (`[g]` or `[b]`)

```bash
gh issue create \
  --repo $GITHUB_REPO \
  --title "[QA] {title}" \
  --label "bug,qa-auto" \
  --body-file <(printf '%s' "$MARKDOWN_BODY")
```

## Step 4 — Backfill

For each bug with a `tc_id`:
- Append created issue key(s) to `$REPORTS/run-analysis-<timestamp>.md` under a `## Filed Tickets` section.
- Do **not** modify TC YAML `jira_key` — that field is reserved for the source TC's linked Jira ticket, not the bug ticket.

If source was `.context/ui-test-bugs-draft.yml`: delete the draft after successful filing (adversarial completion signal per `/qa` orchestrator status detection).

## Step 5 — Summary

```
Filed:
  Jira:   PROJ-123, PROJ-124, PROJ-125
  GitHub: #42, #43
Skipped: 1 flaky
```

Return to orchestrator: filed count per destination.

## Rules

- Never create a ticket without user confirmation (single-item or `[a]ll` batch).
- Never transition existing tickets — creation only. Use `/qa-triage` for transitions.
- Never attach full logs — trim to ≤20 lines of signal. Link to report path instead.
- Never embed secrets from `.env` in issue bodies.
- If MCP / gh auth missing: print the markdown body, do not stall the pipeline.
- Dedup by (spec_path + assertion_signature) within one run; across runs, assume user manages.
