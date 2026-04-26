---
name: qa
description: QA orchestrator. Reads qa/qa-config.yml, checks pipeline prerequisites, routes to plan/codegen/run/sync/triage. Auto-routes to /qa-init if config missing.
---

# /qa — Orchestrator

## Startup

Read `qa/qa-config.yml`. If missing: auto-route to `/qa-init` (scaffold), then re-enter `/qa` after init completes. Do not hard-stop.

Legacy fallback: if `qa-config.yml` exists at project root (old layout), read it but warn:
```
Detected legacy qa-config.yml at project root. New layout nests it under qa/.
Run /qa-init to migrate (moves file, creates missing dirs, updates .gitignore).
Continue with legacy path? [y/n]
```

Resolve and cache — pass inline to all sub-skills, never re-read downstream:

| Var | Source | Default |
|-----|--------|---------|
| `$NAME` | project.name | — |
| `$GITHUB_REPO` | project.github_repo | — |
| `$JIRA_URL` | project.jira.url | — |
| `$JIRA_KEY` | project.jira.project_key | — |
| `$JIRA_QA_STATUS` | project.jira.ready_for_qa_status | `Ready for QA` |
| `$TC_FORMAT` | tc_id.format | `TC-{DOM}-{X}.{Y}.{Z}` |
| `$TC_DOMAINS` | tc_id.domains map | `{web:WEB, mobile:MOB, backend:BE, non_functional:NF}` |
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
| `$BASE_URL` | gen.playwright.base_url (or gen.maestro base URL if playwright absent) | `""` |
| `$MODELS.default` | models.default | `claude-sonnet-4-6` |
| `$MODELS.planner` | models.planner (empty → `$MODELS.default`) | — |
| `$MODELS.validator` | models.validator (empty → `$MODELS.default`) | — |
| `$MODELS.codegen` | models.codegen (empty → `$MODELS.default`) | — |
| `$MODELS.run_analysis` | models.run_analysis (empty → `$MODELS.default`) | — |
| `$MODELS.heal` | models.heal (empty → `$MODELS.default`) | — |
| `$MODELS.sync` | models.sync (empty → `$MODELS.default`) | — |

Apply fallback at resolution time: if a model field is empty string, substitute `$MODELS.default`.

## Prerequisite Checks

Run these checks. Fatal = stop. Warn = show, ask to continue.

| Check | Command | Fatal |
|-------|---------|-------|
| python3 | `python3 --version` | No (warn) |
| pyyaml | `python3 -c "import yaml"` | No (warn) |

If `$GEN.playwright.enabled`:

| Check | Command | Fatal |
|-------|---------|-------|
| npx | `npx --version` | Yes |
| playwright | `npx playwright --version` | Yes |
| packages | `npm ls typescript @playwright/test @types/node --depth=0 2>&1` | No (warn) |
| jq | `jq --version` | No (warn — required for run analysis) |

If `$GEN.maestro.enabled`:

| Check | Command | Fatal |
|-------|---------|-------|
| maestro | `maestro --version` | Yes |

If `$GEN.xcui.enabled`:

| Check | Command | Fatal |
|-------|---------|-------|
| xcodebuild | `xcodebuild -version` | Yes |

If `$GEN.api.enabled`:

| Check | Command | Fatal |
|-------|---------|-------|
| framework-runtime | `node --version` (supertest) OR `python3 --version` (pytest) OR `mvn --version` (rest-assured) — based on `$GEN.api.framework` | Yes |

If `$GEN.a11y.enabled` (requires `$GEN.playwright.enabled` or standalone playwright install):

| Check | Command | Fatal |
|-------|---------|-------|
| @axe-core/playwright | `npm ls @axe-core/playwright --depth=0 2>&1` | No (warn — install on first codegen) |

If `$GEN.vrt.enabled`: needs Playwright runtime (same as playwright check).

If `$GEN.performance.enabled`:

| Check | Command | Fatal |
|-------|---------|-------|
| framework | `lighthouse --version` (lighthouse) OR `k6 version` (k6) | Yes |

If `$GEN.security.enabled`:

| Check | Command | Fatal |
|-------|---------|-------|
| framework | `zap.sh -version` (zap) OR `nuclei -version` (nuclei) | Yes |

If `$GEN.espresso.enabled`:

| Check | Command | Fatal |
|-------|---------|-------|
| gradle | `./gradlew --version` | Yes |
| adb | `adb version` | No (warn) |

Collect all fatals, show list, stop. Warnings: list, ask `Continue? [y/n]`.

## Pipeline Status

Scan dirs, show status before menu:

```
Pipeline: {$NAME}
──────────────────────────────────────
Phase 0.5  Explore      [not run | ✓ date]   (shown only if $BASE_URL set)
Phase 1    Plan         [not run | ✓ N TCs]
Phase 2    Codegen      [not run | ✓ N specs]
Phase 3    Run          [not run | ✓ pass% | ✗ N failed]
Phase 2.5  Adversarial  [not run | ✓ date]   (shown only if $ADV_URL set)
Phase 4    TestRail     [not run | ✓ date]   (shown only if $TESTRAIL.enabled)
──────────────────────────────────────
Cases: N  |  Web specs: N  |  Mobile flows: N
```

Detection:
- Plan done: `$CASES/**/*.yml` count > 0
- Codegen done: `$TESTS/` has spec/flow files
- Run done: `$REPORTS/run-analysis*.md` exists
- Explore done: `.context/ui-test-discovery.md` exists
- Adversarial done: `.context/ui-test-bugs-draft.yml` absent (completed or discarded)
- TestRail done: `.trsync/mapping.json` exists

## State Auto-routing

Check before showing menu:
1. No `qa/qa-config.yml` → auto-route to `/qa-init`
2. No `$CASES/**/*.yml` → auto-route to `/qa-plan`
3. Cases exist, no specs/flows in `$TESTS/` → auto-route to `/qa-codegen`
4. Otherwise → show menu

## Menu (state 3 only)

```
[i]  init         — scaffold qa/ layout + .gitignore (idempotent)
[p]  plan         — create/update TCs
[c]  codegen      — generate automation
[r]  run          — execute tests + heal
[s]  sync         — PR sync + new TCs
[sd] sync daily   — auto PR→plan→codegen→PR cycle
[t]  triage       — Jira ticket triage
[ci] ci           — set up GitHub Actions
[x]  explore      — live app discovery   (shown only if $BASE_URL set)
[a]  adversarial  — edge-case battery    (shown only if $ADV_URL set)
[tr] testrail     — push TCs to TestRail (shown only if $TESTRAIL.enabled)
[b]  bug          — file failures as Jira/GitHub issues  (shown only if run-analysis exists)
[co] coverage     — regenerate qa/TEST-COVERAGE.md
[re] retire       — deprecate TCs for removed features
[f]  full run     — plan → codegen → run
```

Input is case-insensitive. Accept both `p` and `P`.

## Routing

| Choice | Action |
|--------|--------|
| i | Invoke /qa-init; on return re-enter /qa startup |
| p | Invoke /qa-plan; on return show TC count |
| c | Check framework gate → Invoke /qa-codegen; on return show spec count |
| r | Invoke /qa-run; on return offer adversarial gate if $ADV_URL set |
| s | Invoke /qa-sync |
| sd | Invoke /qa-sync --daily |
| t | Invoke /qa-triage |
| ci | Invoke /qa-ci |
| x | Invoke /qa-explore; store returned `$DISCOVERY_REPORT` in session |
| a | Invoke /qa-adversarial |
| tr | Invoke /qa-testrail |
| b | Invoke /qa-bug |
| co | Invoke /qa-coverage |
| re | Invoke /qa-retire |
| f | Full run — see below |

**Framework gate (before codegen):** If no `gen.*.enabled: true` in config:
```
No framework enabled in qa-config.yml.
Enable: 1. Playwright  2. Maestro  3. XCUI  4. Multiple
```
Write enabled flag(s) to config before proceeding. Multiple = enable all chosen frameworks.

**Explore → Plan handoff:** If `/qa-explore` returned a `$DISCOVERY_REPORT` path, pass it to `/qa-plan` when next invoked. Show:
```
Discovery report available: .context/ui-test-discovery.md
Include in planning? [y/n]
```

**Post-run adversarial gate:** After `/qa-run` returns and `$ADV_URL` is set:
```
Run adversarial tests? [y/n]
```

**Post-run bug gate:** After `/qa-run` returns with failures (fail count > 0):
```
File failures as tickets? [y/n]
```
Route to `/qa-bug` on yes.

**Post-plan/sync TestRail gate:** After `/qa-plan` or `/qa-sync` returns and `$TESTRAIL.enabled`:
```
Push TCs to TestRail? [y/n]
```

**Full run (`f`):**
```
/qa-plan
  → show: N TCs written. Proceed to codegen? [y/n]
/qa-codegen
  → show: N specs written. Proceed to run? [y/n]
/qa-run
  → show: pass rate. Run adversarial? [y/n]  (only if $ADV_URL set)
  → show: Push TCs to TestRail? [y/n]        (only if $TESTRAIL.enabled)
```
User can stop at any gate.

## Rules

- Silent between gates. No prose between tool calls.
- Never read source docs, TCs, or specs in main context. Only read status files and counts.
- Sub-skills do all heavy work via subagents.
- `$DISCOVERY_REPORT` persists in session until explicitly cleared or new explore run.
