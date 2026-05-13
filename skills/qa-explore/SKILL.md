---
name: qa-explore
description: Live app discovery before planning. Crawls web (web-app-auditor) or mobile to feed observed flows into qa-plan. Optional phase — prompted at Phase 0 boundary.
---

# /qa-explore — Live App Discovery (Phase 0.5)

Receives from orchestrator: `$GEN`, `$DOCS`

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

Optional — run before /qa-plan to feed planner with live app observations.

**Modes:** `web` (default) | `mobile` (`--mobile` flag)

---

## Web Track (default)

### Step 0 — Prerequisites

Read `$GEN.playwright.base_url` as `$BASE_URL`. If empty: ask `> App base URL:`.

```bash
curl -s -m 3 -o /dev/null -w "%{http_code}" "$BASE_URL"
```

If unreachable (000): `> App not responding at $BASE_URL — continue anyway? [y/n]`

### Step 1 — Scope

```
> Routes to focus on (Enter = full app):
```

Blank → full app. Paths provided → restrict to those.

### Step 2 — Spawn Discovery Agent

Spawn agent using subagent_type: `web-app-auditor` with:

```
QA discovery mode — do NOT file bug reports. Build a structured map of live app behavior.

BASE_URL: {$BASE_URL}
Scope: {full app | routes: {list}}

Capture:
1. Route inventory — URL, title, purpose (1 sentence each)
2. Interactive elements — forms, modals, multi-step flows; inputs, validation behavior
3. User flows — happy paths, auth barriers encountered
4. Edge case signals — error states, empty states, disabled elements
5. Console errors — JS errors, 4xx/5xx during navigation
6. Teardown hooks — observe network tab for DELETE/reset endpoints. List path, method, scope. Do NOT call them.

Do NOT: submit adversarial payloads, bypass auth, mutate data, navigate off-domain.

Write to .context/ui-test-discovery.md:
  # UI Discovery Report
  Generated: {timestamp}  |  Base URL: {url}  |  Routes visited: N
  ## Route Inventory (table: route, title, purpose)
  ## Flows Discovered
  ## Forms & Inputs
  ## Edge Cases Observed
  ## Console Errors
  ## Teardown Hooks (observed reset/delete endpoints — table: path, method, scope)
  ## Planner Notes (things not obvious from docs alone)

Return: routes visited, flows found, forms found, console errors found.
```

**Fallback:** if `web-app-auditor` agent type is unavailable:
```
Error: web-app-auditor agent type not available.
Install the web-app-auditor plugin to use /qa-explore.
See: https://github.com/anthropics/claude-code — Agent types documentation.
```
Stop. Do not silently continue.

### Step 3 — Gate

Read agent return values. Show:
```
Explore complete: routes={N}  flows={N}  forms={N}  errors={N}
Report: .context/ui-test-discovery.md

Use as planner context? [y/trim/n]
```

- `y` → set `$DISCOVERY_REPORT=.context/ui-test-discovery.md`
- `trim` → pause for user to edit, then set `$DISCOVERY_REPORT`
- `n` → do not set `$DISCOVERY_REPORT`

Return `$DISCOVERY_REPORT` (path or empty) to orchestrator.

---

## Mobile Track (`--mobile`)

### M0 — Prereq

- `$GEN.maestro.enabled` true, else stop with: "Mobile discovery requires gen.maestro.enabled: true in qa-config.yml."
- Ask `> Target: [android/ios]`. Require matching `android_app_id` / `ios_app_id`.
- `maestro list-devices`. Ask `> Device ready? [y/n]`.

### M1 — Capture

Spawn general-purpose subagent with Maestro MCP:

```
Mobile QA discovery — passive only. No mutation, no auth bypass, no form submits beyond nav.

App: {app_id}  Platform: {android|ios}

Steps:
1. launch_app → take_screenshot
2. inspect_view_hierarchy top-level
3. tap_on each top-level destination, screenshot + hierarchy each
4. List interactive elements per screen
5. Capture crash/error dialogs

Write .context/mobile-discovery.md:
  # Mobile Discovery Report
  Generated / App / Platform / Screens N
  ## Screen Inventory
  ## Navigation Map
  ## Interactive Elements
  ## Forms & Inputs
  ## Edge Cases
  ## Planner Notes

Return: screens, flows, forms, crashes.
```

### M2 — Gate

Same as web Step 3. Report = `.context/mobile-discovery.md`.

---

## Rules

- Passive observation only — no adversarial actions.
- Web agent stays within `$BASE_URL` origin; mobile agent stays within the app under test.
- Main context only reads agent return summary — never the full report.
- Agent type unavailability = hard error with install instructions. No silent fallback.
