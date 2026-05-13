---
name: qa-codegen
description: Generate test specs from TCs using Agent A/B information barrier (mechanical redaction + post-write leak check). automation_id backfilled as YAML map. Session-linked reports.
---

# /qa-codegen — Code Generation

Receives from orchestrator: `$CASES`, `$TESTS`, `$MODELS`, `$TC_FORMAT`, `$GEN`, `$QABOT_SESSION`, `$QABOT_FRAMEWORK`, `$DISCOVERY_REPORT` (optional)

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

Active frameworks: any `gen.<framework>.enabled: true` in `$GEN`. If `$QABOT_FRAMEWORK` is set to a specific key, run only that framework.

## Step 0 — Scope + Reset

```
> TCs? [a=all | <ids> | <glob>]
> Reset? [n | api | ui | storage | fixture]
> Reset apply to? [all | <ids>]
```

Filter `$CASES/**/*.yml` to scope. Skip already-automated unless `--force`.

---

## Information Barrier

### Mechanical Redaction (Main Context — before Agent A spawn)

Main context builds sanitized TC list as string substitution — NOT an instruction to Agent A:

```
For each TC in scope:
  Read TC YAML fields
  Copy all fields verbatim
  Replace expected_result value with literal string "REDACTED"
  Result: TC object with expected_result = "REDACTED"
```

This produces `$REDACTED_TC_LIST` — all TC fields intact except `expected_result`.

Build `$EXPECTED_RESULT_MAP` in main context (do NOT write to disk):
```
TC-WEB-1.1.1 → "User is redirected to dashboard"
TC-WEB-1.1.2 → "Error message 'Invalid credentials' shown"
```
Plain text table. Used only for Agent B. Never passed to Agent A.

**TC immutability:** set `QABOT_TC_IMMUTABLE=1` and `QABOT_AGENT_ROLE=agent-a` in env for Agent A spawn. Set `QABOT_AGENT_ROLE=agent-b` for Agent B spawn. Hook (`pre_tool_use.py`) blocks any Write/Edit on existing `qa/cases/**/*.yml` except mutable fields.

### Agent A (spawn with `$MODELS.codegen`, env: QABOT_AGENT_ROLE=agent-a)

- Input: `$REDACTED_TC_LIST` (all TC fields, `expected_result = "REDACTED"`) + QA_CONTEXT if available + DOM snapshots if available
- Task: write complete spec files with `# ASSERT_HERE: {TC_ID}` markers at assertion points
- Output: files to framework root(s)
- **Never receives**: original `expected_result` values, `$EXPECTED_RESULT_MAP`

### Post-Write Leak Check (Main Context — after Agent A writes)

For each TC in scope, for each file Agent A wrote:
```
Extract all substrings of length ≥ 6 chars from the original expected_result
Grep each substring in the written spec file
If any hit found → Agent A leaked expected_result content
  → Delete file, re-run Agent A for that TC only (max 2 retries)
  → If still leaking after 2 retries → surface to user with exact line reference
```

### Agent B (spawn with `$MODELS.codegen`, env: QABOT_AGENT_ROLE=agent-b)

- Input: `$EXPECTED_RESULT_MAP` as inline plain text table ONLY — no access to `$CASES/`
  ```
  TC-WEB-1.1.1 → "User is redirected to dashboard"
  TC-WEB-1.1.2 → "Error message 'Invalid credentials' shown"
  ```
  Agent B receives: this map + the marker locations in written spec files
  Agent B does NOT receive: TC YAML paths, spec file paths, test structure beyond marker locations
- Task: replace each `# ASSERT_HERE: {TC_ID}` with correct assertion derived from expected_result
- Output: overwrite Agent A files in-place

**Partial failure:** if Agent A fails for a subset of TCs, skip those IDs in Agent B. Log skipped TC IDs. Never abort entire run for partial failures.

---

## automation_id Backfill

After Agent B completes, update each TC YAML:
- Set `automation_status: automated`
- Set `automation_id` as YAML map keyed by framework config key:

```yaml
automation_id:
  playwright: qa/tests/web/specs/auth/tc-web-1-1-1.spec.ts
```

Multi-framework: merge new framework key into existing map. Never overwrite existing framework keys — only add new ones.

```yaml
automation_id:
  playwright: qa/tests/web/specs/auth/tc-web-1-1-1.spec.ts
  maestro: qa/tests/mobile/flows/tc-mob-1-1-1.yaml    # added, playwright preserved
```

Immutability: only `automation_id` and `automation_status` fields updated. Never touch steps, title, expected_result, id.

---

## Post-Write Lint (block on hit)

Antipattern grep across emitted files. Fail loud, route to healer or user:
- Playwright: `\.first\(\)\.locator`, `\.all\(\)` w/o prior `.count()`, `waitForTimeout`, `page\.waitForSelector` w/o timeout, hardcoded `http://`/`https://` URL outside config
- Maestro: `wait` w/o condition, hardcoded appId, `assertVisible` w/o timeout on dynamic elements
- All: TC ID present in tag comment (other than the required `// {TC_ID}` tag)

---

## Report

Write `$REPORTS/codegen-{framework}-$QABOT_SESSION.md` for each framework run:
```
# Codegen Report — {framework} — {QABOT_SESSION}
Generated: {timestamp}
TCs in scope: N | Specs written: N | Skipped (already automated): N | Failed: N
Skipped TC IDs: [list if any]
Leak check: passed / N files retried / N surfaced to user
```

---

## Framework: Playwright → `$GEN.playwright.root`

Skip entire section if `$GEN.playwright.enabled` is false.

### File Structure
```
<root>/
├── pages/       # Page Objects
├── specs/       # Test specs
├── fixtures/    # Setup/teardown
└── data/        # Test data
```

### Locator Priority
| Priority | Locator | Use when |
|----------|---------|----------|
| 1 | `getByRole` | interactive elements with ARIA role |
| 2 | `getByLabel` | form fields with labels |
| 3 | `getByTestId` | elements with `data-testid` |
| 4 | `getByText` | static text, buttons |
| 5 | `locator(css)` | only if above unavailable |

### Page Object Rules
```typescript
class LoginPage {
  readonly emailInput = this.page.getByLabel('Email');
  async login(email: string, password: string) { ... }
}
```
- Locators as readonly properties at top
- Actions as async methods — no assertions inside page objects
- Specs import page objects, call actions, then assert

### Spec Rules
- Tag each `test()` with TC ID: `// {TC_ID}`
- Group by feature in `describe()` blocks
- `# ASSERT_HERE: {TC_ID}` marks where Agent B fills assertions
- Never hardcode selectors, URLs, credentials, or test data in specs

### Sharding (playwright.config.ts)
```typescript
const shardTotal = Number(process.env.SHARD_TOTAL ?? {$GEN.playwright.shards});
const shardIndex = Number(process.env.SHARD_INDEX ?? 1);
export default defineConfig({
  workers: Number(process.env.PW_WORKERS ?? {$GEN.playwright.workers}),
  shard: shardTotal > 1 ? { current: shardIndex, total: shardTotal } : undefined,
  reporter: [['json', { outputFile: 'qa/reports/results-playwright.json' }], ['list']],
});
```

---

## Framework: Maestro → `$GEN.maestro.root`

Skip entire section if `$GEN.maestro.enabled` is false.

### File Structure
```
<root>/
├── suites/      # smoke.yaml, regression.yaml, feature-e2e.yaml
├── flows/       # {tc-id-slug}.yaml — one per TC
├── subflows/    # shared fragments
└── data/        # variable files
```

### Flow Rules
- Flow name matches TC ID slug: `tc-mob-1-1-1-slug`
- Set `appId` at top using platform-specific value from `$GEN.maestro.android_app_id` / `ios_app_id`
- All values via `${VAR}` — no hardcoded strings
- `# ASSERT_HERE: {TC_ID}` marks assertion point for Agent B

---

## Framework: XCUI → `$GEN.xcui.root`

Skip entire section if `$GEN.xcui.enabled` is false.

### File Structure
```
<root>/
├── Pages/       # XCUIElement wrappers
├── Tests/       # XCTestCase subclasses
├── Helpers/     # shared setup
└── Data/        # test data
```

### Test Rules
- Tag each test: `// {TC_ID}`
- Group by feature in separate XCTestCase subclasses
- `// ASSERT_HERE: {TC_ID}` marks where Agent B fills assertions
- Never hardcode bundle IDs, credentials, or test data

---

## Framework: API → `$GEN.api.root`

Skip if `$GEN.api.enabled` is false. Routes TCs where `platform: backend`.

File structure and rules per `$GEN.api.framework` (supertest/pytest/rest-assured) — same patterns as other frameworks. Info barrier applies unchanged.

---

## Framework: a11y → `$GEN.a11y.root`

Skip if `$GEN.a11y.enabled` is false. Routes `type: accessibility`. Requires `@axe-core/playwright`.

- WCAG level from `$GEN.a11y.wcag_level`
- One spec per TC; `// ASSERT_HERE: {TC_ID}` — Agent B fills `expect(results.violations)` check

---

## Framework: VRT → `$GEN.vrt.root`

Skip if `$GEN.vrt.enabled` false. Routes `type: visual`. Playwright `toHaveScreenshot`.

- `// ASSERT_HERE: {TC_ID}` — Agent B fills screenshot call + mask list
- First run needs `--update-snapshots`

---

## Framework: Performance → `$GEN.performance.root`

Skip if `$GEN.performance.enabled` false. Routes `type: performance`.

- Lighthouse or k6 per `$GEN.performance.framework`
- `// ASSERT_HERE: {TC_ID}` — Agent B fills score/threshold assertions

---

## Framework: Security → `$GEN.security.root`

Skip if `$GEN.security.enabled` false. Routes `type: security`.

- ZAP or nuclei per `$GEN.security.framework`
- Target from `$GEN.security.target_url`, fallback `$GEN.playwright.base_url`
- Emit `SECURITY-NOTICE.md` if target matches common prod TLDs

---

## Framework: Espresso → `$GEN.espresso.root`

Skip if `$GEN.espresso.enabled` false. Routes `platform: android`. Kotlin instrumented tests.

- `// ASSERT_HERE: {TC_ID}` → Agent B fills `.check(matches(...))`

---

## Adding a New Framework

1. Add `gen.<name>:` block to `qa-config.yml` template
2. Add `## Framework: <Name>` section following same structure
3. Agent A/B pattern applies unchanged — only file format differs

---

## Return Contract

Return to orchestrator: spec count written per framework, TC backfill count, skipped TC IDs (if any), report paths.
