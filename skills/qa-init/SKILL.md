---
name: qa-init
description: One-time scaffold. Optionally distributes qabot skills from a cloned repo to ~/.claude/skills/. Creates qa/ layout, copies qa-config.yml template, writes .env.example, seeds sync log, extends .gitignore. Idempotent.
---

# /qa-init — Bootstrap + Scaffold

Two modes:

1. **First install** — pass `--from <path>` pointing to a cloned qabot repo. Distributes all skills globally to `~/.claude/skills/`, optionally wires hooks, then scaffolds this project's `qa/` directory.
2. **Already installed** — run without args. Scaffolds (or repairs) `qa/` only.

Receives from orchestrator: nothing (qa-init runs before config exists).

---

## Step -1 — Distribute Framework (only if `--from <path>` provided)

Parse `--from <path>` from invocation args. If absent, skip to Step 0.

**Validate source:**
```bash
SRC="<resolved --from path>"
[ -d "$SRC/skills/qa" ] || error "Not a qabot repo — missing skills/qa/"
```

**RTK check (warn if missing):**
```bash
which rtk || echo "Warning: rtk not found. Install: https://github.com/rtk-ai/rtk — required before running /qa."
```

**Distribute skills:**
```bash
SKILLS_DST="$HOME/.claude/skills"
mkdir -p "$SKILLS_DST"

for skill_dir in "$SRC"/skills/qa*/; do
  skill_name=$(basename "$skill_dir")
  if [ -d "$SKILLS_DST/$skill_name" ]; then
    ask "  $skill_name already exists. Overwrite? [y/n]"
    # n → skip this skill; y → overwrite
  fi
  cp -r "$skill_dir" "$SKILLS_DST/$skill_name"
done
```

Show one line per installed skill:
```
  ✓ qa → ~/.claude/skills/qa
  ✓ qa-init → ~/.claude/skills/qa-init
  ...
```

**Optionally wire hooks:**
```
Wire qabot hooks into ~/.claude/settings.json?
Enforces info-barrier (Agent A/B) and blocks destructive bash patterns.
[y] yes  [n] skip
```

If yes, merge into `~/.claude/settings.json` under `hooks` — append only, never overwrite existing entries:
```json
{
  "PreToolUse": [
    {
      "matcher": "Bash|WebFetch|Write|Edit|Read|Grep",
      "hooks": [
        { "type": "command", "command": "python3 <SRC>/hooks/pre_tool_use.py" }
      ]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "*",
      "hooks": [
        { "type": "command", "command": "python3 <SRC>/hooks/post_tool_use.py" }
      ]
    }
  ]
}
```

Use the actual resolved `$SRC` path (not a variable) so the hook works from any project.

**Summary after distribution:**
```
Framework distributed from: /path/to/cloned/qabot
  Skills installed: qa, qa-init, qa-plan, qa-codegen, qa-run, qa-sync,
                    qa-triage, qa-ci, qa-explore, qa-adversarial, qa-bug,
                    qa-retire, qa-testrail
  Hooks wired: [yes | skipped]

Skills are now global — subsequent projects only need /qa-init (no --from).
Continuing with project scaffold...
```

---

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

---

## Step 1 — Create Directory Layout

Everything under `qa/`. Never write qa-* files at project root (except `.gitignore`).

```bash
mkdir -p qa/cases qa/docs qa/tests qa/reports qa/templates qa/.context qa/.trsync
```

---

## Step 2 — Copy Canonical Templates

Resolve framework source: `$SRC` if `--from` was provided, else two dirs up from this SKILL.md (i.e. the globally installed skill's parent).

```bash
FW_ROOT="${SRC:-$(dirname "$(dirname "$(realpath "$0")")")}"
cp "$FW_ROOT/templates/tc.yml" qa/templates/tc.yml
[ "$HAS_CONFIG" = "0" ] && cp "$FW_ROOT/templates/qa-config.yml" qa/qa-config.yml
```

Prompt user to fill required fields after init completes:
```
Next: open qa/qa-config.yml and set:
  - project.name
  - project.github_repo
  - project.jira.url, project.jira.project_key
  - tc_format: A | B | C  (default B — single step block)
  - gen.*.enabled (at least one framework)
```

---

## Step 3 — Write `.env.example`

```bash
cat > qa/.env.example <<'EOF'
# TestRail (only if testrail.enabled: true in qa-config.yml)
TR_USER=""
TR_API_KEY=""
TR_PASSWORD=""

# Anthropic — used by sub-agents invoked from skills
ANTHROPIC_API_KEY=""

# Stagehand (only if stagehand.enabled: true in qa-config.yml)
# BROWSERBASE_API_KEY=""   # only needed if stagehand.env: BROWSERBASE
# STAGEHAND_ENV="LOCAL"    # LOCAL | BROWSERBASE
# Note: qa/.stagehand-cache.json is local only — not committed
EOF
```

Never overwrite existing `qa/.env.example` — if present, skip.

---

## Step 4 — Seed Sync Log

If `qa/sync-log.md` absent:
```bash
printf 'last_sync: %s\n--- sync history ---\n' "$(date +%Y-%m-%d)" > qa/sync-log.md
```

---

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

# Stagehand (local cache — not committed, each user builds their own)
qa/.stagehand-cache.json

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

Write to `<project-root>/.gitignore` (NOT `qa/.gitignore`). If the `# --- qa-concise ---` marker already exists, skip the whole block. Otherwise append.

**Committed by default** (do NOT add to .gitignore):
- `qa/cases/**` — TC YAMLs
- `qa/tests/**` — spec / flow / test files (but NOT build outputs above)
- `qa/qa-config.yml`
- `qa/sync-log.md`
- `qa/templates/`
- `qa/.env.example`

---

## Step 6 — Optional Framework Installs

Read `qa/qa-config.yml` (if just copied, all `enabled: false` — skip). If any framework was pre-enabled, offer install:

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

### Stagehand (`stagehand.enabled: true`)
```
Install Stagehand? [y/n]
```
If yes:
```bash
npm install @browserbasehq/stagehand zod
```
Note: Stagehand cache (`qa/.stagehand-cache.json`) is local — not committed. Each developer and CI run builds their own cache. Delete to force re-resolution after major UI changes.

---

## Step 7 — Summary

Print exactly:
```
qa-init complete.

  qa/qa-config.yml       [created | kept]
  qa/templates/tc.yml    [created | kept]
  qa/{cases,docs,tests,reports,templates}   created
  qa/.context/ qa/.trsync/                  created
  qa/.env.example        [created | kept]
  qa/sync-log.md         [created | kept]
  .gitignore             [updated | already installed]

Next: fill qa/qa-config.yml required fields, then run /qa.
See docs/TC-SCHEMA.md and docs/CONFIG-SCHEMA.md for field reference.
```

---

## Rules

- Never overwrite a file without explicit `[o] overwrite` confirmation.
- Never commit `.env` or `.trsync/mapping.json` — enforced via `.gitignore`.
- Never scaffold outside `qa/` except `.gitignore` at project root.
- Never install framework deps without user `[y]`.
- Idempotent: re-running after first init must be a no-op (except distribution step, which checks before overwriting).
