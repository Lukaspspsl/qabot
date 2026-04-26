---
name: qa-run
description: Execute tests, analyse failures, heal flaky locators/timing. Tags low-confidence fixes as HEAL_REVIEW for user approval before re-run.
---

# /qa-run — Run + Analyse + Heal

Receives from orchestrator: `$TESTS`, `$REPORTS`, `$MODELS`, `$GEN`, `$BASE_URL`, `$REPORTS_RETENTION`, `$NOTIFY`

## Step 0 — Pre-check

**Retention prune** (before any new reports written). If `$REPORTS_RETENTION > 0`:
```bash
find "$REPORTS" -type f -mtime +$REPORTS_RETENTION -name '*.md' -delete 2>/dev/null
find "$REPORTS" -type f -mtime +$REPORTS_RETENTION -name '*.json' -delete 2>/dev/null
find "$REPORTS" -type f -mtime +$REPORTS_RETENTION -name '*.txt' -delete 2>/dev/null
find "$REPORTS" -type f -mtime +$REPORTS_RETENTION -name '*.xcresult' -delete 2>/dev/null
```
Skip silently if `$REPORTS_RETENTION == 0` (keep forever).

Determine active frameworks from `$GEN`. For each enabled:

**Playwright:**
- `$GEN.playwright.root/specs/` has `.spec.ts` files
- `npx tsc --noEmit` passes (warn if fails, don't block)
- If `$BASE_URL` empty: ask `> Base URL?` and use for this run
- Ask: `> App running at $BASE_URL? [y/n]`

**Maestro:**
- `$GEN.maestro.root/flows/` has `.yaml` files
- Ask: `> Target platform: [android/ios/both]`
  - Android requires `$GEN.maestro.android_app_id` set; warn if empty
  - iOS requires `$GEN.maestro.ios_app_id` set; warn if empty
- `maestro list-devices` — show output, ask to confirm device/emulator ready
- Pass `ANDROID_APP_ID=$GEN.maestro.android_app_id` / `IOS_APP_ID=$GEN.maestro.ios_app_id` as env vars when running flows

**XCUI:**
- `$GEN.xcui.root/Tests/` has `.swift` files
- Ask: `> Simulator/device ready? Scheme: $GEN.xcui.scheme [y/n]`

**Espresso:**
- `$GEN.espresso.root/app/src/androidTest/` has `.kt`/`.java` files
- Ask: `> Emulator/device connected? Package: $GEN.espresso.package [y/n]`

**VRT:**
- `$GEN.vrt.root/specs/` has `.vrt.spec.ts` files
- Ask: `> Base URL? Baselines exist (first run needs --update-snapshots)? [y/n]`

**Performance / Security:**
- Present if `$GEN.performance.enabled` or `$GEN.security.enabled`.
- Ask target URL confirmation (fallback `$GEN.playwright.base_url`). Security scans also require explicit "authorized to scan" confirmation.

If multiple frameworks enabled: `Run which? 1. Playwright  2. Maestro  3. XCUI  4. All`

## Step 1 — Run

**Playwright:**
```bash
npx playwright test 2>&1 | tee $REPORTS/run-output-web.txt
```
Config in `playwright.config.ts` — JSON reporter to `$REPORTS/results-web.json`.

**Sandbox auto-detect:** if output matches `bootstrap_check_in.*Permission denied|mach.*denied|sandbox.*denied`, set session flag `SANDBOX_OFF=1`. Re-run with `dangerouslyDisableSandbox: true` for all subsequent Playwright/Chromium Bash calls in this run. Log once: `Sandbox disabled — Chromium IPC blocked.`

**Maestro:**
```bash
maestro test $GEN.maestro.root 2>&1 | tee $REPORTS/run-output-mobile.txt
```

**XCUI:**
```bash
xcodebuild test -scheme $GEN.xcui.scheme -destination 'platform=iOS Simulator,name=iPhone 16' \
  -resultBundlePath $REPORTS/xcui-results.xcresult 2>&1 | tee $REPORTS/run-output-xcui.txt
```

## Step 2 — Analyse (subagent, model: `$MODELS.run_analysis`)

**Playwright:** slim results before spawning:
```bash
jq '[.suites[].specs[] | {title, ok, duration: .results[0].duration, error: .results[0].errors[0].message[:300]? // null}]' \
  $REPORTS/results-web.json > $REPORTS/results-web-slim.json
```

Spawn subagent per framework:
```
Read run output + slim results.
Produce:
1. Pass/fail summary (total, passed, failed, skipped, flaky)
2. Failure categories: locator | assertion | timeout | setup
3. Per-feature breakdown
4. Flaky tests (passed on retry)
Write to $REPORTS/run-analysis-{web|mobile|xcui}.md
Return: pass rate, fail count, top failure categories
```

## Step 3 — Gate

Show: pass rate, failure summary per framework.

If failures:
```
1. Auto-heal
2. Show failures for manual fix
3. Skip
```

## Step 4 — Heal (if chosen, subagent, model: `$MODELS.heal`)

Internal loop, max 3 cycles. Healer:
1. Snapshot TC YAMLs (sha256 per file) before patching.
2. Patch failing files. Tag `// HEAL_FIX: [reason] | confidence: X.XX` (or `HEAL_REVIEW` if <0.70).
3. Run **full suite** (not just failing). Detect new regressions introduced by patch.
4. Append entry per patch to `$REPORTS/heal-log.jsonl`:
   `{"cycle":N,"ts":"...","file":"...","tc":"...","pattern":"locator|timing|setup|race","confidence":0.9,"before_sha":"...","after_sha":"...","result":"pass|fail|regress"}`
5. Re-snapshot TC YAMLs; diff vs step 1. Any change to `expected_result|steps|title|id` ⇒ revert patch, mark `HEAL_REJECTED`, abort cycle.
6. Converge: all green ⇒ exit. New failure ⇒ next cycle. Cap=3 ⇒ surface `no convergence` to user with last delta.

**Fix only:** locators, timing (condition-based waits, never `waitForTimeout`), navigation, preconditions, state isolation.
**Never change:** expected results, assertion values, TC IDs, step logic.

Write summary to `$REPORTS/heal-{web|mobile|xcui}.md`. Return: cycles, patches, HEAL_REVIEW count, convergence status.

## Step 4.25 — Flake Gate (post-heal)

After heal converges, re-run healed specs only with `--repeat-each=3` before declaring green.

**Playwright:**
```bash
npx playwright test {healed_spec_paths} --repeat-each=3 2>&1 | tee $REPORTS/flake-gate-web.txt
```

Any failure across the 3 reps ⇒ mark spec flaky, feed into Step 4.5 quarantine list. All-pass ⇒ green.

Skip if heal did not run or no specs patched.

## Step 4.5 — Flaky Quarantine

After analysis, if any test marked flaky (passed on retry):
```
{N} flaky test(s) detected:
  - specs/auth/tc-web-1-1-1.spec.ts — TC-WEB-1.1.1
  - flows/tc-mob-2-1-1.yaml — TC-MOB-2.1.1
Quarantine flagged specs? [y/n]
```

On `y`:
- **Playwright:** prepend `.fixme` to the matching `test()` — e.g. `test.fixme('TC-WEB-1.1.1 — …', async ...)`. Comment above: `// FLAKY: quarantined {YYYY-MM-DD} — run N, see qa/reports/flaky.md`.
- **Maestro:** move flow file to `$GEN.maestro.root/flows/_quarantine/` (create dir if absent). Remove from any suite that references it; log pruned suite lines.
- **XCUI:** add `XCTSkip("FLAKY: quarantined {date}")` at top of test function. Comment with TC ID + report reference.

Write `$REPORTS/flaky.md` (append-only):
```markdown
# Flaky Quarantine Log

## {YYYY-MM-DD HH:MM}
- TC-WEB-1.1.1 — specs/auth/tc-web-1-1-1.spec.ts — passed 1/3 retries — run ID {run_id}
- TC-MOB-2.1.1 — flows/tc-mob-2-1-1.yaml — passed 1/2 retries
```

Never modifies TC YAMLs. Quarantine is spec-level only; TC remains active. User un-quarantines manually by removing `.fixme` / restoring file / removing `XCTSkip`.

## Step 5 — HEAL_REVIEW Gate

If heal report contains any `HEAL_REVIEW` tags:
```
{N} changes flagged HEAL_REVIEW (confidence < 0.70)
See: $REPORTS/heal-{framework}.md
Review before re-run? [y/n]
```
- `y` → pause. User inspects/edits flagged files. Confirm when done.
- `n` → proceed to re-run offer without pause.

## Step 6 — Notifications

If `$NOTIFY.slack` or `$NOTIFY.teams` set, post run summary after final results (post once per run, after any re-run).

Payload shape:
```
{$NAME} qa-run — {pass_rate}% ({passed}/{total})
failed={F}  flaky={X}  heal_review={H}
report: {repo_url or local path}
```

Slack (`$NOTIFY.slack`):
```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"text":"<payload>"}' "$NOTIFY.slack"
```

Teams (`$NOTIFY.teams`) — MessageCard:
```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"@type":"MessageCard","text":"<payload>"}' "$NOTIFY.teams"
```

Best-effort. Network failure: log warning, never block return. Skip entirely if both empty.

## Return Contract

Return to orchestrator: pass rate per framework, fail count, HEAL_REVIEW count (if heal ran).

## Rules

- No auto-run without confirmation.
- Healer fixes execution only — never expectations.
- Run each framework fully before starting next.
- Silent except summaries and gates.
