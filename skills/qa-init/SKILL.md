---
name: qa-init
description: One-time scaffold. Copies qabot skills + hooks into project's .claude/ directory (project-local, git-ignored). Creates qa/ layout, copies qa-config.yml template, writes .env.example, seeds sync log, extends .gitignore. Idempotent.
---

# /qa-init — Bootstrap + Scaffold

Two modes:

1. **First install** — pass `--from <path>` pointing to a cloned qabot repo. Installs all skills and hooks into this project's `.claude/` directory, then scaffolds `qa/`.
2. **Already installed** — run without args. Scaffolds (or repairs) `qa/` only.

All qabot skills and hooks live inside the project under `.claude/` — zero global installs, zero collision with user's own global hooks or skills.

Receives from orchestrator: nothing (qa-init runs before config exists).

---

## Step -1 — Install Framework into Project (only if `--from <path>` provided)

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

**Install skills into project `.claude/skills/`:**
```bash
PROJECT_ROOT="$(pwd)"
SKILLS_DST="$PROJECT_ROOT/.claude/skills"
mkdir -p "$SKILLS_DST"

for skill_dir in "$SRC"/skills/qa*/; do
  skill_name=$(basename "$skill_dir")
  if [ -d "$SKILLS_DST/$skill_name" ]; then
    ask "  $skill_name already exists in .claude/skills/. Overwrite? [y/n]"
    # n → skip this skill; y → overwrite
  fi
  cp -r "$skill_dir" "$SKILLS_DST/$skill_name"
done
```

Show one line per installed skill:
```
  ✓ qa → .claude/skills/qa
  ✓ qa-init → .claude/skills/qa-init
  ...
```

**Install hooks into project `.claude/hooks/`:**
```bash
HOOKS_DST="$PROJECT_ROOT/.claude/hooks"
mkdir -p "$HOOKS_DST"
cp "$SRC/hooks/pre_tool_use.py" "$HOOKS_DST/pre_tool_use.py"
cp "$SRC/hooks/post_tool_use.py" "$HOOKS_DST/post_tool_use.py"
```

**Wire hooks in project `.claude/settings.json`:**

Read existing `.claude/settings.json` if present. Merge hook entries — append only, never overwrite existing entries:

```json
{
  "PreToolUse": [
    {
      "matcher": "Bash|WebFetch|Write|Edit|Read|Grep",
      "hooks": [
        { "type": "command", "command": "python3 .claude/hooks/pre_tool_use.py" }
      ]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "*",
      "hooks": [
        { "type": "command", "command": "python3 .claude/hooks/post_tool_use.py" }
      ]
    }
  ]
}
```

Use relative path `python3 .claude/hooks/pre_tool_use.py` — Claude Code resolves relative paths from the project root, so this works without hardcoding the user's absolute path.

If `.claude/settings.json` already contains a qabot hook entry (grep for `.claude/hooks/pre_tool_use.py`), skip — idempotent.

**Summary after install:**
```
Framework installed into: .claude/
  Skills: qa, qa-init, qa-plan, qa-codegen, qa-run, qa-sync,
          qa-triage, qa-ci, qa-explore, qa-adversarial, qa-bug,
          qa-retire, qa-testrail
  Hooks:  .claude/hooks/pre_tool_use.py
          .claude/hooks/post_tool_use.py
  Config: .claude/settings.json [created | updated]

Skills and hooks are project-local — no global installs.
Teammates get hook wiring automatically (settings.json committed).
Reinstall skills/hooks: /qa-init --from <path-to-qabot>
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

Resolve framework source: `$SRC` if `--from` was provided, else two dirs up from this SKILL.md (i.e. the project-local skill's parent at `.claude/skills/`).

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
See docs/TC-SCHEMA.md and docs/CONFIG-SCHEMA.md for field reference.
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

**Principle:** everything under `qa/` is ignored by default except `qa/tests/` (the actual test specs). Config, cases, docs, reports, templates, state — all local. Users opt-in to committing more by removing lines from `.gitignore`. `.claude/settings.json` IS committed so teammates get hook wiring without reinstall.

```
# --- qa-concise ---
# qabot project-local install (reinstall via /qa-init --from <path-to-qabot>)
.claude/skills/qa*/
.claude/hooks/pre_tool_use.py
.claude/hooks/post_tool_use.py

# Everything under qa/ is local by default — only tests/ is committed
qa/
!qa/tests/
!qa/tests/**

# Exclude test runner build artifacts from qa/tests/
qa/tests/**/.playwright/
qa/tests/**/playwright-report/
qa/tests/**/test-results/
qa/tests/**/blob-report/
qa/tests/**/.maestro/
qa/tests/**/build/
qa/tests/**/DerivedData/
qa/tests/**/.gradle/
*.xcuserstate

# Stagehand (local cache — each user builds their own)
qa/.stagehand-cache.json

# Node / OS
node_modules/
.DS_Store
*.log
*.swp
.idea/
.vscode/
# --- /qa-concise ---
```

Write to `<project-root>/.gitignore` (NOT `qa/.gitignore`). If the `# --- qa-concise ---` marker already exists, skip the whole block. Otherwise append.

**Committed by default:**
- `qa/tests/**` — spec / flow / test files (excluding build outputs above)
- `.claude/settings.json` — hook wiring; teammates inherit this on clone

**Git-ignored by default (opt-in by removing from .gitignore):**
- `qa/qa-config.yml` — local workflow config
- `qa/cases/**` — TC YAMLs (can be committed if team wants shared test plan)
- `qa/docs/` — source docs
- `qa/reports/` — run analysis, heal logs
- `qa/templates/` — reference templates
- `qa/sync-log.md` — sync state
- `qa/.env`, `qa/.env.example` — creds and cred templates
- `.claude/skills/qa*/`, `.claude/hooks/*.py` — reinstall per developer

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

  .claude/skills/qa*/          [installed | skipped — already present]
  .claude/hooks/               [installed | skipped — already present]
  .claude/settings.json        [created | updated | skipped]
  qa/qa-config.yml             [created | kept]
  qa/templates/tc.yml          [created | kept]
  qa/{cases,docs,tests,reports,templates}   created
  qa/.context/ qa/.trsync/                  created
  qa/.env.example              [created | kept]
  qa/sync-log.md               [created | kept]
  .gitignore                   [updated | already installed]

Next: fill qa/qa-config.yml required fields, then run /qa.
See docs/TC-SCHEMA.md and docs/CONFIG-SCHEMA.md for field reference.
```

---

## Rules

- Never overwrite a file without explicit `[o] overwrite` confirmation.
- Never commit `.env` or `.trsync/mapping.json` — enforced via `.gitignore`.
- Never scaffold outside `qa/` or `.claude/` except `.gitignore` at project root.
- Never install framework deps without user `[y]`.
- Skills and hooks are git-ignored — reinstalled per developer via `--from`.
- `.claude/settings.json` IS committed — teammates get hook wiring on clone.
- Idempotent: re-running after first init must be a no-op (each step checks before acting).
