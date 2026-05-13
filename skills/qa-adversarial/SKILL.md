---
name: qa-adversarial
description: Edge-case battery against sandbox URL after qa-run passes. subagent_type=ui-adversarial. Optional phase — prompted at Phase 3 boundary.
---

# /qa-adversarial — Edge-Case Battery (Phase 2.5)

Receives from orchestrator: `$ADV_URL`, `$CASES`, `$REPORTS`, `$TC_FORMAT`, `$TC_DOMAINS`, `$QABOT_SESSION`

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

Optional — run after /qa-run passes to surface edge-case failures as TC candidates.

## Step 0 — Prerequisites

If `$ADV_URL` empty:
```
Phase 2.5 requires adversarial.base_url in qa-config.yml.
Set it to an isolated sandbox — never production.
```
Stop.

```bash
curl -s -m 3 -o /dev/null -w "%{http_code}" "$ADV_URL"
```
If unreachable: `> Sandbox not responding — continue anyway? [y/n]`

Verify `$ADV_URL` differs from `gen.playwright.base_url`. If same:
```
Error: adversarial.base_url must differ from gen.playwright.base_url.
Never run adversarial tests against the dev server.
```
Stop.

## Step 1 — Route Selection

Auto-detect from `$REPORTS/run-analysis-playwright-*.md` (latest): extract routes from spec paths.
Heuristic: `specs/auth/` → `/login /register`, `specs/checkout/` → `/checkout /cart`, etc.

Show detected routes:
```
Detected: /login  /register  /checkout
Use these? [y/edit/add]
```

If < 2 detected: ask `> Routes to test (e.g. /login /checkout):`.

## Step 2 — Spawn Adversarial Agent

```bash
mkdir -p .context/adversarial-screenshots
```

Spawn agent using subagent_type: `ui-adversarial` with:

```
Run full adversarial battery.

BASE_URL: {$ADV_URL}
Routes: {list}

Isolated sandbox — authorized to:
- Submit forms with boundary/invalid/empty inputs
- Rapid repeated interactions
- Keyboard-only flows
- Direct URL access to protected routes
- Viewport resize mid-interaction

Do NOT navigate off-domain. Do NOT use SQL injection or XSS payloads.
Run all tests — do not stop on first failure.

Output STEP_PASS/STEP_FAIL per standard format.
Save STEP_FAIL screenshots to: .context/adversarial-screenshots/
```

**Fallback:** if `ui-adversarial` agent type is unavailable:
```
Error: ui-adversarial agent type not available.
Install the ui-adversarial plugin to use /qa-adversarial.
See: https://github.com/anthropics/claude-code — Agent types documentation.
```
Stop. Do not silently continue.

## Step 3 — Translate STEP_FAILs

For each STEP_FAIL line from agent output, write draft TC stub to `.context/ui-test-bugs-draft.yml`:

```yaml
drafts:
  - id: DRAFT-{N}
    source_step: "{route}#{test-id}"
    finding: "{expected} → {actual}"
    screenshot: ".context/adversarial-screenshots/{file}"
    proposed_tc:
      id: ""
      title: "[Discovered] {title}"
      platform: web
      type: functional
      priority: medium
      automation_status: manual
      preconditions:
        - "{derived from route/auth context}"
      steps: "{action from step}"
      expected_result: "{expected from STEP_FAIL}"
      jira_key: ""
      automation_id: {}
```

IDs assigned from `$TC_FORMAT` once approved.

## Step 4 — Gate

```
Adversarial complete: routes={N}  tests={N}  pass={N}  fail={N}
Session: {$QABOT_SESSION}
Drafts: .context/ui-test-bugs-draft.yml

[a] approve all  [r] review each  [s] save for later  [n] discard
```

**Approve all:** assign next available TC IDs per `$TC_FORMAT`, write to `$CASES/`, remove from draft file. New TCs get `schema_version: 1`.

**Review each:**
```
DRAFT-{N}: {title}
Route: {route}  Finding: {expected} → {actual}
Screenshot: {path}
[a]pprove  [e]dit  [s]kip  [d]iscard
```

**Save:** leave `.context/ui-test-bugs-draft.yml` — `/qa-sync` picks it up.

**Discard:** delete draft file.

## Rules

- `$ADV_URL` must differ from `$GEN.playwright.base_url` — never test adversarially against dev server.
- Approved TCs: `automation_status: manual` until explicitly run through /qa-codegen.
- Screenshots are primary evidence — always linked in draft TC.
- Agent runs autonomously — no user interaction mid-battery.
- Agent type unavailability = hard error with install instructions. No silent fallback.
