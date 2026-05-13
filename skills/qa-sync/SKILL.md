---
name: qa-sync
description: Sync TCs against merged PRs since last run. RTK PR fetch. Session-linked reports. Interactive by default, --daily flag auto-approves covered features.
---

# /qa-sync — PR Sync

Receives from orchestrator: `$CASES`, `$DOCS`, `$TESTS`, `$SYNC_LOG`, `$MODELS`, `$TC_FORMAT`, `$TC_DOMAINS`, `$GITHUB_REPO`, `$JIRA_URL`, `$JIRA_KEY`, `$GEN`, `$NOTIFY`, `$QABOT_SESSION`

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

**Mode:** default = interactive. `--daily` flag = auto-approve covered features, gate only new/uncovered, open PR at end.

## Step 1 — Read Last Sync Date

Read `$SYNC_LOG` first line: `last_sync: YYYY-MM-DD`
If absent: use 30 days ago, note to user.

## Step 2 — Fetch Merged PRs

```bash
rtk gh pr list --state merged --base main --limit 50 --json number,title,body,files
```

If `$GITHUB_REPO` set, add `--repo "$GITHUB_REPO"`. Filter by merged date >= `$LAST_SYNC`.

RTK filters PR output to relevant fields only, reducing token consumption.

## Step 3 — Classify PRs (subagent, model: `$MODELS.sync`)

Spawn subagent with PR list + `$CASES/` dir listing (not TC contents).

Subagent classifies each PR's changed files:
- `covered` — existing TCs reference this feature area → no new TCs needed
- `uncovered` — feature area has TCs but changed behavior not covered → new TCs needed
- `new-feature` — no `$CASES/` subdirectory for this area → new dir + TCs
- `skip` — config, CI, docs, deps → ignore

Return: classified list only. No file writes.

## Step 4 — User Gate

Show summary:
```
PRs since $LAST_SYNC: N
  covered:     X — skip
  uncovered:   Y — need TCs
  new-feature: Z — need TCs + new dir
  skipped:     W
```

Interactive mode: `Generate TCs for uncovered/new-feature? [y/n/select]`
Daily mode: auto-approve if Y=0 and Z=0 → stop with "No new coverage needed". Otherwise gate only on new-feature items.

## Step 5 — Generate New TCs

For each approved PR feature, spawn planner agent (same rules as /qa-plan Phase 1):
- Input: PR body + changed file list as source material, existing `$CASES/` for ID continuity
- Continue ID sequence from highest existing TC number in that domain group
- Use `$TC_FORMAT` and `$TC_DOMAINS` for new IDs
- Write `.yml` files to `$CASES/<feature>/`
- Append rows to `$CASES/test-plan.csv` (11-column format)
- New TCs: `automation_status: manual`, `schema_version: 1`
- Track list as `$NEW_TC_FILES`

**Immutability:** never modify existing TC YAML fields except `jira_key`/`automation_id` backfill.

**Jira auto-link:** same as /qa-plan — subagent attempts match if `$JIRA_KEY` set. Never block on failure.

## Step 6 — Offer Codegen

Interactive mode: `Run /qa-codegen for new TCs? [y/n]`
Daily mode: auto-run codegen if any new TCs written.

If yes/auto: invoke /qa-codegen passing `$NEW_TC_FILES`.

## Step 7 — Write Report

Write `$REPORTS/sync-$QABOT_SESSION.md`:
```
# Sync Report — {QABOT_SESSION}
Date: {timestamp}  |  PRs processed: N
New TCs: N | New specs: N
PRs: #X #Y
```

## Step 8 — Update Sync Log

Overwrite first line of `$SYNC_LOG`, append history:
```
last_sync: YYYY-MM-DD
--- sync history ---
YYYY-MM-DD: N new TCs (PRs: #X #Y) session={QABOT_SESSION}
```

## Step 9 — Daily Mode Only: Open PR

```bash
BRANCH="qa/sync-$(date +%Y%m%d)"
git checkout -b "$BRANCH"
git add $CASES/ $TESTS/
git commit -m "test: qa sync $(date +%Y-%m-%d) — N TCs, M specs (PRs: #X #Y)"
git push -u origin "$BRANCH"
gh pr create \
  --repo $GITHUB_REPO \
  --title "test: qa sync $(date +%Y-%m-%d)" \
  --body "PRs: #X #Y | New TCs: N | New specs: M | Session: $QABOT_SESSION"
```

Show PR URL. Stop.

Interactive mode: skip Step 9. User commits manually.

## Step 10 — Notifications (daily, post-PR)

Skip if both `$NOTIFY.*` empty or no PR opened.

Payload:
```
{$NAME} qa-sync — N new TCs, M specs
session={QABOT_SESSION}  PRs: #X #Y
review: <PR URL>
```

Best-effort. Never block on network fail.

## Rules

- Never modify existing TC YAML fields except `jira_key`, `automation_id`, `automation_status`.
- Never delete existing TCs or test files.
- Never push or merge directly — PR only (daily mode) or manual (interactive).
- If git working tree dirty in daily mode: warn, stop.
