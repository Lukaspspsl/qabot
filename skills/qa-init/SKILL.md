---
name: qa-init
description: One-time scaffold. Creates qa/ layout, copies qa-config.yml template, writes .env.example, seeds sync log, extends .gitignore. Idempotent.
---

# /qa-init — Scaffold a qa-concise Project

One-time setup. Creates the full `qa/` directory layout, copies `qa-config.yml`, writes `.env.example`, seeds sync log, and writes an extensive `.gitignore`. Idempotent — safe to re-run.

Receives from orchestrator: nothing (qa-init runs before config exists).

## Step 0 — Detect Current State

```bash
PROJECT_ROOT="$(pwd)"
HAS_CONFIG=$([ -f "qa/qa-config.yml" ] && echo 1 || echo 0)
HAS_QA_DIR=$([ -d "qa" ] && echo 1 || echo 0)
```

If `HAS_CONFIG=1`:
```
qa/qa-config.yml already exists.
[k] keep (just ensure dirs + gitignore)  [o] overwrite  [c] cancel
```

## Step 1 — Create Directory Layout

Everything under `qa/`. Never write qa-* files at project root (except `.gitignore`).

```bash
mkdir -p qa/cases qa/docs qa/tests qa/reports qa/templates qa/.context qa/.trsync
```

## Step 2 — Copy Canonical Templates

Framework repo path resolved via skill location. Copy the two canonical templates into the consumer project so users can read / extend them without cloning qa-concise.

```bash
# Framework root = two dirs up from this SKILL.md
FW_ROOT="$(dirname "$(dirname "$(realpath "$0")")")/.."  # pseudocode — resolve actually via skill metadata
cp "$FW_ROOT/templates/tc.yml" qa/templates/tc.yml
# qa-config.yml: only copy if not keeping existing
[ "$HAS_CONFIG" = "0" ] && cp "$FW_ROOT/templates/qa-config.yml" qa/qa-config.yml
```

Prompt user to fill required fields after init completes:
```
Next: open qa/qa-config.yml and set:
  - project.name
  - project.github_repo
  - project.jira.url, project.jira.project_key
  - gen.*.enabled (at least one framework)
```

## Step 3 — Write `.env.example`

```bash
cat > qa/.env.example <<'EOF'
# TestRail (only if testrail.enabled: true in qa-config.yml)
TR_USER=""
TR_API_KEY=""
TR_PASSWORD=""

# Anthropic — used by sub-agents invoked from skills
ANTHROPIC_API_KEY=""
EOF
```

Never overwrite existing `qa/.env.example` — if present, skip.

## Step 4 — Seed Sync Log

If `qa/sync-log.md` absent:
```bash
printf 'last_sync: %s\n--- sync history ---\n' "$(date +%Y-%m-%d)" > qa/sync-log.md
```

## Step 5 — Write Extensive `.gitignore`

Idempotent append. Read existing `.gitignore` (if present); append only lines not already present.

**Principle:** only test scripts + case YAMLs + config + sync log + templates commit. Everything else local.

```
# --- qa-concise ---
# Secrets
qa/.env
qa/.env.*
!qa/.env.example

# Local state (per-clone)
qa/.trsync/
qa/.context/

# Reports (run analysis, heal logs, results json — never committed)
qa/reports/

# Source docs — commented default. Uncomment if your team does not share these.
# qa/docs/

# Node / Playwright
node_modules/
qa/tests/**/.playwright/
qa/tests/**/playwright-report/
qa/tests/**/test-results/
qa/tests/**/blob-report/

# Maestro
qa/tests/**/.maestro/

# XCUI / Android
qa/tests/**/build/
qa/tests/**/DerivedData/
qa/tests/**/.gradle/
*.xcuserstate

# Editor / OS
.DS_Store
*.log
*.swp
.idea/
.vscode/
# --- /qa-concise ---
```

Write to `<project-root>/.gitignore` (NOT `qa/.gitignore`). If the `# --- qa-concise ---` marker already exists, skip the whole block (already installed). Otherwise append.

**Committed by default** (do NOT add to .gitignore):
- `qa/cases/**` — TC YAMLs
- `qa/tests/**` — spec / flow / test files (but NOT build outputs above)
- `qa/qa-config.yml`
- `qa/sync-log.md`
- `qa/templates/`
- `qa/.env.example`

## Step 6 — Optional Framework Installs

Read `qa/qa-config.yml` (if it was just copied, defaults are all `enabled: false` — skip). If any framework flipped on by the user before `/qa-init` runs, offer install:

### Playwright (`gen.playwright.enabled: true`)
```
Install Playwright browsers? [y/n]
```
If yes:
```bash
npx playwright install
```

### Maestro (`gen.maestro.enabled: true`)
```bash
maestro --version || echo "Install: brew tap mobile-dev-inc/tap && brew install maestro"
```
Show command; do not install automatically (requires brew).

### XCUI (`gen.xcui.enabled: true`)
Verify `xcodebuild -version`. Warn if missing.

## Step 7 — Summary

Print exactly:
```
qa-init complete.

  qa/qa-config.yml       [created | kept]
  qa/{cases,docs,tests,reports,templates}   created
  qa/.context/ qa/.trsync/                  created
  qa/.env.example        [created | kept]
  qa/sync-log.md         [created | kept]
  .gitignore             [updated | already installed]

Next: fill qa/qa-config.yml required fields, then run /qa.
```

## Rules

- Never overwrite a file without explicit `[o] overwrite` confirmation.
- Never commit `.env` or `.trsync/mapping.json` — enforced via `.gitignore`.
- Never scaffold outside `qa/` except `.gitignore` at project root.
- Never install framework deps without user `[y]`.
- Idempotent: re-running after first init must be a no-op (except updating `last_sync` not touched).
