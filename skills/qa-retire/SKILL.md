# /qa-retire — Deprecate TCs for Removed Features

Marks `deprecated: true` on TCs whose underlying feature was removed. Never deletes. Detection reuses `/qa-sync` PR classifier.

Receives from orchestrator: `$CASES`, `$TESTS`, `$SYNC_LOG`, `$GITHUB_REPO`, `$MODELS`, `$GEN`

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

```
Detect removed features from:
  [p] merged PRs since last sync   (uses $SYNC_LOG last_sync date)
  [m] manual list                  (paste TC IDs or feature-group names)
  [c] cancel
```

## Step 1 — Candidate Detection (PR mode)

Spawn subagent with `$MODELS.sync`. Input:
- `gh pr list --repo $GITHUB_REPO --state merged --search "merged:>$LAST_SYNC"` output
- Per-PR file list: `gh pr view <n> --json files`

Subagent classifies each PR:
- **removal** — deletions dominate; removed routes/components/endpoints match feature areas
- **other** — skip

Output: list of `{ pr: N, removed_features: [names], evidence: "" }`.

Never reads TC YAMLs in this step.

## Step 2 — TC Match

Main context lists `$CASES/**/*.yml` via `find`. Subagent receives file paths + per-TC `{id, title, source_docs, steps[0..1]}` projection (never full body).

For each removed feature → matching TCs via:
- `source_docs` path overlap
- title/step keyword match (>70% token overlap with feature name)

Output: `{ tc_id, file_path, match_confidence, reason }`.

## Step 3 — Confirm Gate

```
Retire candidates (N):
  1. [0.92] TC-WEB-3.1.1 — Legacy dashboard widget drag    | PR #412 removed /dashboard-v1
  2. [0.74] TC-WEB-3.1.2 — Dashboard widget resize         | PR #412 removed /dashboard-v1
  3. [0.68] TC-MOB-2.4.1 — Beta referral banner tap        | PR #418 removed referral module

Confirm:
  [1..N]  inspect (shows full TC body)
  [a]ll   retire all (confidence ≥ 0.80 auto; < 0.80 still asks per-item)
  [s]kip N,N
  [c]ancel
```

Default threshold: auto-approve ≥ 0.80 under `[a]ll`. Below threshold always prompts.

## Step 4 — Apply

For each confirmed TC:
- Read YAML
- Set `deprecated: true`
- Preserve all other fields (immutability rule — never edits `id`, `title`, `steps`, `expected_result`, `preconditions`, `type`, `platform`, `priority`)
- Write back

If `automation_id` set: note in report — linked spec should be removed separately (not auto-deleted; user decides).

## Step 5 — Report + Log

Write `$REPORTS/retire-{YYYYMMDD-HHMMSS}.md`:
```markdown
# Retire Run — 2026-04-22

Retired N TCs:
- TC-WEB-3.1.1 (PR #412, confidence 0.92)
- ...

Linked specs (manual cleanup):
- qa/tests/web/specs/dashboard-widget.spec.ts — TC-WEB-3.1.1
- ...
```

Append `$SYNC_LOG`:
```
retired_at: 2026-04-22
retired_count: N
```

## Step 6 — Downstream Filter Reminder

Print:
```
Deprecated TCs excluded from:
  /qa-run             (skips specs linked to deprecated TCs)
  /qa-testrail        (sets TestRail case to "Deprecated" section on next push)
  /qa-coverage        (excluded from automated %; counted separately)

Spec files NOT auto-deleted — review retire report.
```

## Rules

- Never deletes TC files. Only flips `deprecated: true`.
- Never deletes spec files — surfaces for human removal.
- Never retires without user confirmation (per-item or `[a]ll`).
- Immutability: only `deprecated`, `jira_key`, `automation_id`, `automation_status` may change on existing TC. This skill only touches `deprecated`.
- PR mode requires `gh auth`. Fall back to manual list if missing.
- Requires `templates/tc.yml` with `deprecated` field (P0.4 — already shipped).
