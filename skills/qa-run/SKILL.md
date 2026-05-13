---
name: qa-run
description: Execute tests via RTK, analyse failures, heal flaky locators/timing. Framework names = config keys. Session-linked reports.
---

# /qa-run — Run + Analyse + Heal

Receives from orchestrator: `$TESTS`, `$REPORTS`, `$MODELS`, `$GEN`, `$BASE_URL`, `$REPORTS_RETENTION`, `$NOTIFY`, `$QABOT_SESSION`, `$QABOT_FRAMEWORK`

## Step 0 — Pre-check

**Retention prune** (before any new reports written). If `$REPORTS_RETENTION > 0`:
```bash
find "$REPORTS" -type f -mtime +$REPORTS_RETENTION \( -name '*.md' -o -name '*.json' -o -name '*.txt' -o -name '*.xcresult' \) -delete 2>/dev/null
```

Determine active frameworks from `$GEN` (filter by `$QABOT_FRAMEWORK` if set). For each enabled:

**playwright:**
- `$GEN.playwright.root/specs/` has `.spec.ts` files
- `npx tsc --noEmit` passes (warn if fails, don't block)
- If `$BASE_URL` empty: ask `> Base URL?`
- Ask: `> App running at $BASE_URL? [y/n]`

**maestro:**
- `$GEN.maestro.root/flows/` has `.yaml` files
- Ask: `> Target platform: [android/ios/both]`
- `maestro list-devices` — confirm device/emulator ready
- Pass `ANDROID_APP_ID=$GEN.maestro.android_app_id` / `IOS_APP_ID=$GEN.maestro.ios_app_id`

**xcui:**
- `$GEN.xcui.root/Tests/` has `.swift` files
- Ask: `> Simulator/device ready? Scheme: $GEN.xcui.scheme [y/n]`

**espresso:**
- Ask: `> Emulator/device connected? Package: $GEN.espresso.package [y/n]`

**vrt:**
- Ask: `> Base URL? Baselines exist (first run needs --update-snapshots)? [y/n]`

**performance / security:**
- Confirm target URL. Security scans require explicit "authorized to scan" confirmation.

If multiple frameworks enabled and `$QABOT_FRAMEWORK` not set:
```
Run which? 1. playwright  2. maestro  3. xcui  4. All
```

---

## Step 1 — Run

**playwright:**
```bash
rtk test "npx playwright test {scope_flags}" 2>&1 | tee $REPORTS/run-output-playwright-$QABOT_SESSION.txt
```
Config in `playwright.config.ts` — JSON reporter to `$REPORTS/results-playwright-$QABOT_SESSION.json`.

**Sandbox auto-detect:** if output matches `bootstrap_check_in.*Permission denied|mach.*denied|sandbox.*denied`:
```
Sandbox denied during Chromium launch. Disable sandbox for ONE retry? [y/n]
```
On `y`: re-run with `dangerouslyDisableSandbox: true` for this command only. Never persist. Never auto-flip.

**maestro:**
```bash
rtk test "maestro test $GEN.maestro.root" 2>&1 | tee $REPORTS/run-output-maestro-$QABOT_SESSION.txt
```

**xcui:**
```bash
xcodebuild test -scheme $GEN.xcui.scheme -destination 'platform=iOS Simulator,name=iPhone 16' \
  -resultBundlePath $REPORTS/xcui-results-$QABOT_SESSION.xcresult 2>&1 | tee $REPORTS/run-output-xcui-$QABOT_SESSION.txt
```

RTK shows only failures + summary — slim output is the intent. Full output still saved to txt for reference.

---

## Step 2 — Analyse (subagent, model: `$MODELS.run_analysis`)

**playwright:** slim results before spawning:
```bash
jq '[.suites[].specs[] | {title, ok, duration: .results[0].duration, error: .results[0].errors[0].message[:300]? // null}]' \
  $REPORTS/results-playwright-$QABOT_SESSION.json > $REPORTS/results-playwright-slim-$QABOT_SESSION.json
```

Spawn subagent per framework:
```
Read run output + slim results.
Produce:
1. Pass/fail summary (total, passed, failed, skipped, flaky)
2. Failure categories: locator | assertion | timeout | setup
3. Per-feature breakdown
4. Flaky tests (passed on retry)
Write to $REPORTS/run-analysis-{framework}-$QABOT_SESSION.md
Return: pass rate, fail count, top failure categories
```

Report filename uses framework config key: `run-analysis-playwright-{session}.md`, `run-analysis-maestro-{session}.md`, `run-analysis-xcui-{session}.md`.

---

## Step 3 — Gate

Show: pass rate, failure summary per framework.

If failures:
```
1. Auto-heal
2. Show failures for manual fix
3. Skip
```

---

## Step 4 — Heal (if chosen, subagent, model: `$MODELS.heal`)

Internal loop, max 3 cycles. Healer:
1. Snapshot TC YAMLs (sha256 per file) before patching.
2. Patch failing files. Tag `// HEAL_FIX: [reason] | confidence: X.XX` (or `HEAL_REVIEW` if <0.70).
3. Run full suite (not just failing). Detect regressions introduced by patch.
4. Append per patch to `$REPORTS/heal-log.jsonl`:
   `{"cycle":N,"ts":"...","file":"...","tc":"...","pattern":"locator|timing|setup|race","confidence":0.9,"before_sha":"...","after_sha":"...","result":"pass|fail|regress"}`
5. Re-snapshot TC YAMLs; diff vs step 1. Any change to `expected_result|steps|title|id` → revert patch, mark `HEAL_REJECTED`, abort cycle.
6. Converge: all green → exit. New failure → next cycle. Cap=3 → surface `no convergence` with last delta.

**Fix only:** locators, timing (condition-based waits, never `waitForTimeout`), navigation, preconditions, state isolation.
**Never change:** expected results, assertion values, TC IDs, step logic.

Write summary to `$REPORTS/heal-{framework}-$QABOT_SESSION.md`.

---

## Step 4.25 — Flake Gate (post-heal)

Re-run healed specs only with `--repeat-each=3` before declaring green.

**playwright:**
```bash
npx playwright test {healed_spec_paths} --repeat-each=3 2>&1 | tee $REPORTS/flake-gate-playwright-$QABOT_SESSION.txt
```

Any failure across 3 reps → mark spec flaky, feed into Step 4.5. All-pass → green.

---

## Step 4.5 — Flaky Quarantine

After analysis, if any test marked flaky:
```
{N} flaky test(s) detected:
  - specs/auth/tc-web-1-1-1.spec.ts — TC-WEB-1.1.1
Quarantine flagged specs? [y/n]
```

On `y`:
- **playwright:** prepend `.fixme` to matching `test()`. Comment: `// FLAKY: quarantined {YYYY-MM-DD} — run $QABOT_SESSION, see qa/reports/flaky.md`
- **maestro:** move flow to `flows/_quarantine/`. Remove from suites.
- **xcui:** add `XCTSkip("FLAKY: quarantined {date}")` with TC ID + report ref.

Append to `$REPORTS/flaky.md`:
```markdown
## {YYYY-MM-DD HH:MM} — session {QABOT_SESSION}
- TC-WEB-1.1.1 — specs/auth/tc-web-1-1-1.spec.ts — passed 1/3 retries
```

Never modifies TC YAMLs.

---

## Step 5 — HEAL_REVIEW Gate

If heal report contains `HEAL_REVIEW` tags:
```
{N} changes flagged HEAL_REVIEW (confidence < 0.70)
See: $REPORTS/heal-{framework}-{session}.md
Review before re-run? [y/n]
```

---

## Step 6 — Notifications

If `$NOTIFY.slack` or `$NOTIFY.teams` set, post run summary after final results.

Payload:
```
{$NAME} qa-run — {pass_rate}% ({passed}/{total})
session={QABOT_SESSION} failed={F} flaky={X} heal_review={H}
report: {repo_url or local path}
```

Best-effort. Network failure: log warning, never block return.

---

## Return Contract

Return to orchestrator: pass rate per framework, fail count, HEAL_REVIEW count (if heal ran), report paths.

Report naming convention:
- `run-output-{framework}-{session}.txt` — raw RTK output
- `run-analysis-{framework}-{session}.md` — analysis subagent report
- `heal-{framework}-{session}.md` — heal summary
- `results-{framework}-{session}.json` — raw test runner JSON

Framework = config key: `playwright`, `maestro`, `xcui`, `api`, `a11y`, `vrt`, `performance`, `security`, `espresso`.

## Rules

- No auto-run without confirmation.
- Healer fixes execution only — never expectations.
- Run each framework fully before starting next.
- Silent except summaries and gates.
- All RTK wrapping transparent — output same as direct command, just token-optimized.
