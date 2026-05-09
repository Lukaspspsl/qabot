---
name: qa-codegen
description: Generate test specs from TCs using Agent A/B information barrier (assertion independence). Supports any framework enabled in qa-config gen.* block.
---

# /qa-codegen — Code Generation

Receives from orchestrator: `$CASES`, `$TESTS`, `$MODELS`, `$TC_FORMAT`, `$GEN`, `$DISCOVERY_REPORT` (optional)

Active frameworks: any `gen.<framework>.enabled: true` in `$GEN`.

## Step 0 — Scope + Reset

```
> TCs? [a=all | <ids> | <glob>]
> Reset? [n | api | ui | storage | fixture]
> Reset apply to? [all | <ids>]
```

Filter `$CASES/**/*.yml` to scope. Skip already-automated unless `--force`.
`api` reset requires `## Teardown Hooks` in `$DISCOVERY_REPORT`; if missing, warn and offer `fixture`.
Pass `RESET_STRATEGY` + endpoints to Agent A. Page object emits `resetState()`; `beforeEach` calls it only for selected TCs.

## Info Barrier (all frameworks — preserves assertion independence)

**TC immutability:** set `QABOT_TC_IMMUTABLE=1` in env for both Agent A and Agent B spawns. Hook (`pre_tool_use.py`) blocks any Write/Edit on existing `qa/cases/**/*.yml` except mutable fields (`jira_key`, `automation_id`, `automation_status`). Backfill step below stays compatible.

**Agent A** (spawn with `$MODELS.codegen`):
- Input: all `$CASES/**/*.yml` with `expected_result` field **redacted** (`"REDACTED"`)
- Task: write complete files with `# ASSERT_HERE: {TC_ID}` markers
- Output: files to framework root(s)

**Main context only:**
- Build lookup map inline: `{ "TC-WEB-1.1.1": "actual expected result", ... }` from original YAMLs
- Do NOT write map to disk

**Agent B** (spawn with `$MODELS.codegen`):
- Input: lookup map as inline text only — no access to `$CASES/`
- Task: replace each `# ASSERT_HERE: {TC_ID}` with correct assertion
- Output: overwrite Agent A files

**Partial failure:** If Agent A fails for a subset of TCs, skip those IDs in Agent B. Log skipped TC IDs. Continue — never abort entire run for partial failures.

**Backfill:**
- Update each TC YAML: set `automation_id` and `automation_status: automated`
- Multiple frameworks: `automation_id` stores comma-separated IDs (`playwright:specs/auth/tc-web-1-1-1.spec.ts,maestro:flows/tc-mob-1-1-1.yaml`)
- Immutability: only `automation_id` and `automation_status` fields. Never touch steps, title, expected_result, id.

## Post-Write Lint (block on hit)

Antipattern grep across emitted files. Fail loud, route to healer or user:
- Playwright: `\.first\(\)\.locator`, `\.all\(\)` w/o prior `.count()`, `waitForTimeout`, `page\.waitForSelector` w/o timeout, hardcoded `http://`/`https://` URL outside config
- Maestro: `wait` w/o condition, hardcoded appId, `assertVisible` w/o timeout on dynamic elements
- All: TC ID present in tag comment

## Info Barrier Diff (Agent A leak check)

After Agent A writes, grep each emitted file for any substring (≥6 chars) from corresponding TC `expected_result`. Hit ⇒ Agent A peeked. Reject file, re-run Agent A for that TC. Max 2 retries then surface to user.

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
// pages/LoginPage.ts
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
- Use fixtures for auth state, test data
- `# ASSERT_HERE: {TC_ID}` marks where Agent B fills assertions
- Never hardcode selectors, URLs, credentials, or test data in specs

### Sharding (playwright.config.ts)
Emit config honoring `$GEN.playwright.shards` + `$GEN.playwright.workers`. Respect CI env (`SHARD_INDEX`, `SHARD_TOTAL`):
```typescript
const shardTotal = Number(process.env.SHARD_TOTAL ?? {$GEN.playwright.shards});
// SHARD_INDEX is 1-based to match Playwright's shard.current convention and CI matrix values.
const shardIndex = Number(process.env.SHARD_INDEX ?? 1);
export default defineConfig({
  workers: Number(process.env.PW_WORKERS ?? {$GEN.playwright.workers}),
  shard: shardTotal > 1 ? { current: shardIndex, total: shardTotal } : undefined,
  reporter: [['json', { outputFile: 'qa/reports/results-web.json' }], ['list']],
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
├── subflows/    # shared fragments: login.yaml, navigation.yaml
└── data/        # variable files
```

### Flow Rules
- Flow name matches TC ID slug: `tc-mob-1-1-1-slug`
- Set `appId` at top of each flow using the platform-specific value:
  - Android flows: `appId: ${ANDROID_APP_ID}` (resolved from `$GEN.maestro.android_app_id`)
  - iOS flows: `appId: ${IOS_APP_ID}` (resolved from `$GEN.maestro.ios_app_id`)
- If only one platform targeted, omit the other; if both, generate separate flow variants under `flows/android/` and `flows/ios/`
- All values via `${VAR}` — no hardcoded strings, IDs, credentials
- Extract repeated sequences (≥2 flows use it) into `subflows/`
- Subflow invocation: `- runFlow: ../subflows/login.yaml`
- `# ASSERT_HERE: {TC_ID}` marks assertion point for Agent B

### Suite Rules
```yaml
# suites/smoke.yaml
flows:
  - ../flows/tc-mob-1.*.yaml  # P1 only
```
Tags: `smoke` (P1), `regression` (P1+P2), `feature-e2e` (full suite)

---

## Framework: XCUI → `$GEN.xcui.root`

Skip entire section if `$GEN.xcui.enabled` is false.

### File Structure
```
<root>/
├── Pages/       # XCUIElement wrappers (screen objects)
├── Tests/       # XCTestCase subclasses
├── Helpers/     # shared setup, credentials, launch args
└── Data/        # test data (plist or json)
```

### Screen Object Rules
```swift
// Pages/LoginScreen.swift
struct LoginScreen {
    let app: XCUIApplication
    var emailField: XCUIElement { app.textFields["email-input"] }
    func login(email: String, password: String) { ... }
}
```
- Element accessors as computed vars using accessibility identifiers
- Actions as methods — no assertions in screen objects
- Tests import screen objects, call actions, then assert

### Test Rules
- Tag each test with TC ID in comment: `// {TC_ID}`
- Group by feature in separate XCTestCase subclasses
- Use `setUp()` / `tearDown()` for launch args and test data
- `// ASSERT_HERE: {TC_ID}` marks where Agent B fills assertions
- Never hardcode bundle IDs, credentials, or test data in test files
- Use accessibility identifiers, not index-based queries

---

## Framework: API → `$GEN.api.root`

Skip entire section if `$GEN.api.enabled` is false. Routes TCs where `platform: backend`.

### File Structure (per `$GEN.api.framework`)

**supertest** (Node/TS):
```
<root>/
├── clients/     # axios/supertest wrappers per service
├── specs/       # *.spec.ts — one describe per feature
├── fixtures/    # request/response bodies, auth tokens
└── data/        # seed payloads
```

**pytest** (Python):
```
<root>/
├── clients/     # requests.Session subclasses
├── tests/       # test_*.py
├── conftest.py  # fixtures
└── data/
```

**rest-assured** (Java):
```
<root>/
├── clients/     # RequestSpecification builders
├── tests/       # *Test.java
└── data/
```

### Rules
- Base URL from `$GEN.api.base_url` — never hardcode.
- Auth tokens via fixtures / `conftest.py`, never inline.
- One assertion block per TC: status code + response shape + response body field checks.
- Schema validation preferred (ajv / pydantic / json-schema) over field-by-field assertions where TC `expected_result` describes structure.
- Tag each test with TC ID: `// {TC_ID}` (TS/Java) or `# {TC_ID}` (py).
- `// ASSERT_HERE: {TC_ID}` / `# ASSERT_HERE: {TC_ID}` marker for Agent B.
- Never commit real tokens. Use `.env` + framework-specific env loader.

### Info Barrier Applies Unchanged
Agent A receives redacted TCs + writes client calls with markers. Agent B fills response assertions from lookup map only.

---

## Framework: a11y (axe-core Playwright) → `$GEN.a11y.root`

Skip entire section if `$GEN.a11y.enabled` is false. Routes TCs where `type: accessibility`. Requires `@axe-core/playwright` dependency.

### File Structure
```
<root>/
├── specs/       # *.a11y.spec.ts
├── fixtures/    # axe config, ignored rules
└── data/        # page URL map
```

### Rules
- Use `AxeBuilder` from `@axe-core/playwright`.
- WCAG level from `$GEN.a11y.wcag_level` → `.withTags(['wcag2a','wcag2aa'])` etc.
- One spec per TC; navigate to page under test, run `.analyze()`, assert `violations` per TC `expected_result`.
- Never suppress violations globally — per-rule disables only, with comment referencing TC or ticket.
- Example shape:
  ```typescript
  test('TC-WEB-5.1.1 — checkout page meets WCAG 2.1 AA', async ({ page }) => {
    await page.goto('/checkout');
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    // ASSERT_HERE: TC-WEB-5.1.1
  });
  ```
- Agent B assertion typically: `expect(results.violations).toEqual([])` or allow-listed violation count.

### Separate Root
`$GEN.a11y.root` is distinct from `$GEN.playwright.root` so a11y runs can be scheduled independently (heavier, slower). Playwright config in a11y root should extend the main one only if it exists.

---

## Framework: VRT → `$GEN.vrt.root`

Skip if `$GEN.vrt.enabled` false. Routes `type: visual`. Playwright `toHaveScreenshot`.

```
<root>/
├── specs/            # *.vrt.spec.ts
├── fixtures/
├── __screenshots__/  # baselines, committed
└── data/
```

- One spec per TC, title prefixed TC ID.
- Goto page, wait network idle + `document.fonts.ready`, screenshot.
- `await expect(page).toHaveScreenshot('<slug>.png', { maxDiffPixelRatio: $GEN.vrt.threshold })`.
- Stabilize: `mask: [...]`, `animations: 'disabled'`.
- `// ASSERT_HERE: {TC_ID}` — Agent B fills screenshot call + mask list.
- URLs via `data/pages.ts`, never inline.
- First run needs `--update-snapshots`. Emit note to `$GEN.vrt.root/README.md` if `update_baselines: true`.

---

## Framework: Performance → `$GEN.performance.root`

Skip if `$GEN.performance.enabled` false. Routes `type: performance`. Framework = `$GEN.performance.framework` (`lighthouse` | `k6`).

```
# lighthouse
<root>/{specs,budgets,data}/
# k6
<root>/{scripts,thresholds,data}/
```

- Lighthouse: one `.perf.spec.ts` per TC, runs `lighthouse` npm. Marker `// ASSERT_HERE: {TC_ID}` — Agent B fills `expect(lhr.categories.*.score).toBeGreaterThanOrEqual(X)`.
- k6: one `.k6.js` per TC. `options.thresholds` from expected_result. Marker in `export default function` — Agent B fills `check(res,{...})`.
- URL + budgets from config, never inline.
- Separate root — slow, env-sensitive, don't gate functional CI.

---

## Framework: Security → `$GEN.security.root`

Skip if `$GEN.security.enabled` false. Routes `type: security`. Framework = `$GEN.security.framework` (`zap` | `nuclei`).

```
<root>/{scans,baselines,data}/
```

- Target from `$GEN.security.target_url`, fallback `$GEN.playwright.base_url`. Never prod without user confirm in config.
- ZAP: `scans/<tc-slug>.sh` wrapping `zap-baseline.py` + YAML context. Marker `# ASSERT_HERE: {TC_ID}` — Agent B fills alert-count / allow-listed rules.
- nuclei: `scans/<tc-slug>.sh` wrapping `nuclei -u <target> -t <template>`. Agent B fills findings gate.
- `baselines/<tc-slug>.json` = acknowledged findings. Never auto-update.
- Codegen emits `SECURITY-NOTICE.md` if target matches common prod TLDs.

---

## Framework: Espresso → `$GEN.espresso.root`

Skip if `$GEN.espresso.enabled` false. Routes `platform: android` not routed to Maestro. Kotlin instrumented tests.

```
<root>/app/src/androidTest/java/com/<pkg>/{pages,tests,helpers}/
<root>/build.gradle.kts   # espresso + androidx.test
```

- Screen objects: `onView(withId(...))` / `withContentDescription`. Never `withText` (i18n). No assertions inside.
- Tests: `@RunWith(AndroidJUnit4::class)`, one class per feature. Tag `// {TC_ID}`.
- Async via `IdlingRegistry`, never `Thread.sleep`.
- `// ASSERT_HERE: {TC_ID}` → Agent B fills `.check(matches(...))`.
- Package from `$GEN.espresso.package` via BuildConfig. Creds from `local.properties`.
- Run: `./gradlew connectedAndroidTest`.

Return to orchestrator: spec count written per framework, TC backfill count, skipped TC IDs (if any).

---

## Adding a New Framework

To add support for a new automation language:
1. Add `gen.<name>:` block to `qa-config.yml` template with `enabled`, `root`, and any framework-specific fields
2. Add a new `## Framework: <Name>` section to this skill following the same structure:
   - Skip condition (`if enabled is false`)
   - File structure
   - Element/locator rules
   - Spec/flow/test rules including `ASSERT_HERE` marker syntax
3. Agent A and Agent B pattern applies unchanged — only the file format differs
