---
name: qa-explore
description: Live app discovery before planning. Crawls web (Playwright) or mobile (Maestro) to feed observed flows into qa-plan. Optional phase.
---

# /qa-explore — Live App Discovery (Phase 0.5)

Receives from orchestrator: `$GEN`, `$DOCS`

Optional — run before /qa-plan to feed planner with live app observations.

**Modes:** `web` (default, Playwright) | `mobile` (Maestro). Invocation: `/qa-explore` for web, `/qa-explore --mobile` for mobile. If `--mobile` passed, skip to Mobile track below.

## Step 0 — Prerequisites (web)

Read `$GEN.playwright.base_url` as `$BASE_URL`. If empty: ask `> App base URL:`.

```bash
curl -s -m 3 -o /dev/null -w "%{http_code}" "$BASE_URL"
```

If unreachable (000): `> App not responding at $BASE_URL — continue anyway? [y/n]`

## Step 1 — Scope

```
> Routes to focus on (Enter = full app):
```

Blank → full app. Paths provided → restrict to those.

## Step 2 — Spawn Discovery Agent

Spawn `web-app-auditor` with:

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
6. Teardown hooks — observe network tab for DELETE/reset endpoints (`/api/*/reset`, `DELETE /api/*`). List path, method, scope (per-resource | global). Do NOT call them.

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

## Step 3 — Gate

Read agent return values. Show:
```
Explore complete: routes={N}  flows={N}  forms={N}  errors={N}
Report: .context/ui-test-discovery.md

Use as planner context? [y/trim/n]
```

- `y` → set `$DISCOVERY_REPORT=.context/ui-test-discovery.md`
- `trim` → pause for user to edit, then set `$DISCOVERY_REPORT`
- `n` → do not set `$DISCOVERY_REPORT`

Return `$DISCOVERY_REPORT` (path or empty) to orchestrator. Orchestrator passes it to /qa-plan if set.

---

## Mobile Track (`--mobile`)

### M0 — Prereq
- `$GEN.maestro.enabled` true, else stop.
- Ask `> Target: [android/ios]`. Require matching `android_app_id` / `ios_app_id`.
- `maestro list-devices`. Ask `> Device ready? [y/n]`.

### M1 — Capture
Spawn mobile discovery subagent with Maestro MCP (`mcp__maestro__*`):

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
