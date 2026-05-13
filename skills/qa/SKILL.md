---
name: qa
description: QA orchestrator. Reads qa/qa-config.yml, runs prerequisite checks, generates session ID, routes phases with human approval gates and pre-phase scope prompts.
---

# /qa — Orchestrator

## Step 0 — Config

Read `qa/qa-config.yml`. If missing: auto-route to `/qa-init`, then re-enter `/qa` after init completes.

Legacy fallback: if `qa-config.yml` exists at project root (old layout):
```
Detected legacy qa-config.yml at project root. New layout nests it under qa/.
Run /qa-init to migrate. Continue with legacy path? [y/n]
```

Resolve and cache all config vars. Pass inline to all sub-skills — never re-read downstream.

| Var | Source | Default |
|-----|--------|---------|
| `$NAME` | project.name | — |
| `$GITHUB_REPO` | project.github_repo | — |
| `$JIRA_URL` | project.jira.url | — |
| `$JIRA_KEY` | project.jira.project_key | — |
| `$JIRA_QA_STATUS` | project.jira.ready_for_qa_status | `Ready for QA` |
| `$TC_FORMAT` | tc_id.format | `TC-{DOM}-{X}.{Y}.{Z}` |
| `$TC_DOMAINS` | tc_id.domains map | `{web:WEB, mobile:MOB, backend:BE, non_functional:NF}` |
| `$TC_VERBOSITY` | tc_format | `B` |
| `$CASES` | paths.cases | `qa/cases` |
| `$DOCS` | paths.docs | `qa/docs` |
| `$TESTS` | paths.tests | `qa/tests` |
| `$SYNC_LOG` | paths.sync_log | `qa/sync-log.md` |
| `$REPORTS` | paths.reports | `qa/reports` |
| `$GEN` | gen block | — |
| `$ADV_URL` | adversarial.base_url | `""` |
| `$REPORTS_RETENTION` | reports.retention_days | `30` |
| `$NOTIFY.slack` | notifications.slack_webhook | `""` |
| `$NOTIFY.teams` | notifications.teams_webhook | `""` |
| `$TESTRAIL.enabled` | testrail.enabled | `false` |
| `$TESTRAIL.url` | testrail.url | `""` |
| `$TESTRAIL.project_id` | testrail.project_id | `0` |
| `$TESTRAIL.suite_id` | testrail.suite_id | `0` |
| `$BASE_URL` | gen.playwright.base_url (fallback: first enabled framework base_url) | `""` |
| `$MODELS.default` | models.default | `claude-sonnet-4-6` |
| `$MODELS.planner` | models.planner (empty → `$MODELS.default`) | — |
| `$MODELS.validator` | models.validator (empty → `$MODELS.default`) | — |
| `$MODELS.codegen` | models.codegen (empty → `$MODELS.default`) | — |
| `$MODELS.run_analysis` | models.run_analysis (empty → `$MODELS.default`) | — |
| `$MODELS.heal` | models.heal (empty → `$MODELS.default`) | — |
| `$MODELS.sync` | models.sync (empty → `$MODELS.default`) | — |

---

## Step 1 — Doctor Checks

Run these checks before anything else. Hard-fail on any FAIL item — list all, stop, exit non-zero.

### HARD FAIL

| Check | Command | Failure message |
|-------|---------|----------------|
| RTK installed | `which rtk` | "rtk not found. Install: https://github.com/rtk-ai/rtk — required for token efficiency." |
| API key set | `echo $ANTHROPIC_API_KEY \| wc -c` (> 1) | "ANTHROPIC_API_KEY not set. Pipeline cannot spawn agents." |
| Config valid | `qa/qa-config.yml` exists and parsed above | "qa/qa-config.yml missing or invalid. Run /qa-init." |
| Hooks installed | `.claude/hooks/` contains `pre_tool_use.py` | "qabot hooks not installed. Run /qa-init." |

If any HARD FAIL: show list of all failures, stop. Do not proceed past this step.

### WARN (show, ask to continue)

| Check | Command | Warning message |
|-------|---------|----------------|
| gh auth | `gh auth status 2>&1` (exit 0) | "gh not authenticated. qa-sync and qa-ci will fail." |
| Jira MCP | Jira MCP tool available | "Jira MCP unavailable. Auto-linking and triage will be skipped." |
| TestRail creds | `.env` contains `TR_USER` (only if testrail.enabled) | "TestRail creds not found in .env. /qa-testrail will fail." |
| Obs server | `curl -s -m 2 http://localhost:4000/health` (exit 0) | "Obs server not running. Start: bash obs/start-obs.sh" |

If any WARNs: list them, `Continue? [y/n]`. On `n`: stop.

RTK integration points (for reference):
- `rtk read {file}` — doc reads in qa-plan
- `rtk test {cmd}` — test execution in qa-run
- `rtk gh pr list ...` — PR fetch in qa-sync

### Framework checks (after HARD FAIL cleared)

Run only for enabled frameworks:

**playwright.enabled:**
| Check | Fatal |
|-------|-------|
| `npx --version` | Yes |
| `npx playwright --version` | Yes |
| `npm ls typescript @playwright/test @types/node --depth=0` | Warn |
| `jq --version` | Warn |

**maestro.enabled:**
| Check | Fatal |
|-------|-------|
| `maestro --version` | Yes |

**xcui.enabled:**
| Check | Fatal |
|-------|-------|
| `xcodebuild -version` | Yes |

**api.enabled:**
| Check | Fatal |
|-------|-------|
| Framework runtime (`node`/`python3`/`mvn`) | Yes |

**a11y.enabled:**
| Check | Fatal |
|-------|-------|
| `npm ls @axe-core/playwright --depth=0` | Warn |

**performance.enabled:**
| Check | Fatal |
|-------|-------|
| `lighthouse --version` or `k6 version` | Yes |

**security.enabled:**
| Check | Fatal |
|-------|-------|
| `zap.sh -version` or `nuclei -version` | Yes |

**espresso.enabled:**
| Check | Fatal |
|-------|-------|
| `./gradlew --version` | Yes |
| `adb version` | Warn |

---

## Step 2 — Session Init

Generate session ID:
```bash
QABOT_SESSION=$(openssl rand -hex 4)
```

Set env vars for all sub-skill spawns:
```
QABOT_SESSION=$QABOT_SESSION
QABOT_TC_IMMUTABLE=1
RTK_ENABLED=1
TC_FORMAT=$TC_VERBOSITY
```

Show: `Session: $QABOT_SESSION`

---

## Step 3 — Pipeline Status

Scan dirs, show before menu:

```
Pipeline: {$NAME}   Session: {$QABOT_SESSION}
──────────────────────────────────────────────
Phase 0.5  Explore      [not run | ✓ date]      (shown only if $BASE_URL set)
Phase 1    Plan         [not run | ✓ N TCs]
Phase 2    Codegen      [not run | ✓ N specs]
Phase 3    Run          [not run | ✓ pass% | ✗ N failed]
Phase 2.5  Adversarial  [not run | ✓ date]      (shown only if $ADV_URL set)
Phase 4    TestRail     [not run | ✓ date]       (shown only if $TESTRAIL.enabled)
──────────────────────────────────────────────
Coverage: {N} TCs — WEB:{w} MOB:{m} BE:{b} NF:{n} | Automated: {a}%
```

Detection:
- Plan done: `$CASES/**/*.yml` count > 0
- Codegen done: `$TESTS/` has spec/flow files
- Run done: `$REPORTS/run-analysis-*-{session}.md` exists
- Explore done: `.context/ui-test-discovery.md` exists
- Adversarial done: `.context/ui-test-bugs-draft.yml` absent
- TestRail done: `.trsync/mapping.json` exists

Coverage tally (inline — no subagent):
```bash
find "$CASES" -name "*.yml" | xargs grep -l "schema_version" | wc -l   # total
grep -rl "platform: web" "$CASES" --include="*.yml" | wc -l            # WEB
grep -rl "platform: mobile" "$CASES" --include="*.yml" | wc -l         # MOB
grep -rl "platform: backend" "$CASES" --include="*.yml" | wc -l        # BE
grep -rl "platform: non_functional" "$CASES" --include="*.yml" | wc -l # NF
grep -rl "automation_status: automated" "$CASES" --include="*.yml" | wc -l  # automated
```

Automated% = (automated count / total) * 100.

---

## Step 4 — State Auto-routing

Check before showing menu:
1. No `qa/qa-config.yml` → auto-route to `/qa-init`
2. No `$CASES/**/*.yml` → offer "Run /qa-explore first? [y/N]", then auto-route to `/qa-plan`
3. Cases exist, no specs/flows in `$TESTS/` → auto-route to `/qa-codegen`
4. Otherwise → show menu

---

## Step 5 — Menu

```
[i]  init         — scaffold qa/ layout + .gitignore (idempotent)
[p]  plan         — create/update TCs
[c]  codegen      — generate automation
[r]  run          — execute tests + heal
[s]  sync         — PR sync + new TCs
[sd] sync daily   — auto PR→plan→codegen→PR cycle
[t]  triage       — Jira ticket triage
[ci] ci           — set up GitHub Actions
[x]  explore      — live app discovery       (shown only if $BASE_URL set)
[a]  adversarial  — edge-case battery        (shown only if $ADV_URL set)
[tr] testrail     — push TCs to TestRail     (shown only if $TESTRAIL.enabled)
[b]  bug          — file failures as Jira/GitHub issues   (shown only if run-analysis exists)
[re] retire       — deprecate TCs for removed features
[f]  full run     — plan → codegen → run
```

Input is case-insensitive.

---

## Step 6 — Routing + Phase Gates

### Phase 0 — Explore (optional)

If user selects `[x]` or auto-routing suggests it:
```
Discovery report found / none. Run /qa-explore first? [y/N]
```
Invoke `/qa-explore`. Store `$DISCOVERY_REPORT` in session.

### Phase 1 — Plan

**Pre-phase scope prompt:**
```
Generate TCs for:
[1] All domains
[2] Domain(s)   — select from: WEB MOB BE NF (or custom domains)
[3] Section     — enter feature group name or number
[4] Specific TC IDs — enter comma-separated
```
Set `QABOT_SCOPE` from selection. Pass to qa-plan.

Invoke `/qa-plan`.

**GATE:**
```
Plan complete. {N} TCs written. Report: qa/reports/plan-{session}.md
Review the plan before proceeding? [y/n]
Proceed to codegen? [y/n/edit]
```

On `edit`: pause for user. On `n`: stop. On `y`: continue.

Post-plan TestRail gate (only if `$TESTRAIL.enabled`):
```
Push TCs to TestRail? [y/N]
```

### Phase 2 — Codegen

**Framework gate:** if no `gen.*.enabled: true`:
```
No framework enabled in qa-config.yml.
Enable: 1. Playwright  2. Maestro  3. XCUI  4. Multiple
```
Write enabled flag(s) to config before proceeding.

**Pre-phase scope prompt:**
```
Generate specs for:
[1] All enabled frameworks
[2] Specific framework — select from enabled list
```
Set `QABOT_FRAMEWORK` from selection.

Invoke `/qa-codegen`.

**GATE:**
```
Codegen complete. {N} specs ({framework}). Skipped: {M} (already automated).
Report: qa/reports/codegen-{framework}-{session}.md
Proceed to run? [y/n]
```

### Phase 3 — Run

**Pre-phase scope prompt:**
```
Run:
[1] All enabled frameworks
[2] Specific framework
[3] Specific TC IDs — enter comma-separated
```
Set `QABOT_FRAMEWORK` (or filter) from selection.

Invoke `/qa-run`.

Coverage tally (inline, after run returns):
```bash
# Re-run tally — picks up any automation_status changes from codegen
```
Show updated coverage line:
```
Coverage: {N} TCs — WEB:{w} MOB:{m} BE:{b} NF:{n} | Automated: {a}% | playwright:{p} maestro:{m_f}
```

Adversarial gate (only if `$ADV_URL` set):
```
Run adversarial battery before sync? [y/N]
```
On `y`: invoke `/qa-adversarial`.

**GATE:**
```
Run complete. Pass: {X}% ({framework}). Failures: {N}. Flaky: {F}.
Report: qa/reports/run-analysis-{framework}-{session}.md
Proceed to sync? [y/n/bug-only]
```

Bug gate (if failures > 0):
```
File bugs for failures? [y/N]
```
On `y`: invoke `/qa-bug`.

### Phase 4 — Sync

Invoke `/qa-sync`.

TestRail gate (only if `$TESTRAIL.enabled`):
```
Sync to TestRail? [y/N]
```

**GATE:**
```
Sync complete. {N} new TCs written.
Commit? [y/n]
```
On `y`: show git commands for user to run manually. Never auto-push.

### Full Run ([f])

```
/qa-plan  → GATE: Plan complete. {N} TCs. Proceed to codegen? [y/n]
/qa-codegen → GATE: Codegen complete. {N} specs. Proceed to run? [y/n]
/qa-run   → GATE: Run complete. Pass: {X}%. Run adversarial? [y/N]
           → GATE: Push TCs to TestRail? [y/N]  (only if $TESTRAIL.enabled)
```

User can stop at any gate.

### Other routes

| Choice | Action |
|--------|--------|
| i | Invoke /qa-init; on return re-enter /qa startup |
| s | Invoke /qa-sync |
| sd | Invoke /qa-sync --daily |
| t | Invoke /qa-triage |
| ci | Invoke /qa-ci |
| b | Invoke /qa-bug |
| re | Invoke /qa-retire |
| tr | Invoke /qa-testrail |

---

## Rules

- Silent between gates. No prose between tool calls.
- Never read source docs, TCs, or specs in main context. Only read status files and counts.
- Sub-skills do all heavy work via subagents.
- `$DISCOVERY_REPORT` persists in session until explicitly cleared or new explore run.
- Never auto-push to git. User commits manually.
- `$QABOT_SESSION` is constant for the full session — all reports share the same session ID.
