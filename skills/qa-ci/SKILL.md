---
name: qa-ci
description: Generate GitHub Actions workflows for enabled frameworks. Wires test runs and report uploads on PR.
---

# /qa-ci — GitHub Actions Setup

Receives from orchestrator: `$GITHUB_REPO`, `$GEN`, `$TESTS`, `$REPORTS`

## Step 0 — Check

- Confirm `.github/workflows/` exists. If not: `mkdir -p .github/workflows`.
- `gh auth status` — warn if not authenticated.

## Step 1 — Select Workflows

```
Which workflows to install?
1. Full suite    — runs all tests on schedule + manual trigger
2. PR trigger    — on PR merge, syncs + generates TCs for changed features
3. Auto-healer   — on test failure, attempts heal + creates fix PR
4. All
```

## Step 2 — Write Workflow Files

Write selected workflows to `.github/workflows/`. At write time, substitute actual values from `$GEN` and `$REPORTS` — do NOT write literal variable names into the YAML files. Conditionally include/exclude steps based on which frameworks are enabled.

**Full suite** (`.github/workflows/qa-full.yml`) — example with Playwright enabled, `$REPORTS` = `qa/reports`:
```yaml
name: QA Full Suite
on:
  schedule:
    - cron: '0 6 * * 1-5'
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    # Expand matrix from $GEN.playwright.shards. shards=1 → omit matrix block entirely.
    # shards=N>1 → matrix.shard: [1, 2, ..., N] and fail-fast: false.
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2]   # substitute with [1..$GEN.playwright.shards] at write time
    steps:
      - uses: actions/checkout@v4
      # Include setup-node + playwright steps only if $GEN.playwright.enabled
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npx playwright install --with-deps
      - run: npx playwright test
        env:
          BASE_URL: ${{ vars.QA_BASE_URL }}
          SHARD_INDEX: ${{ matrix.shard }}
          SHARD_TOTAL: 2   # substitute with $GEN.playwright.shards at write time
          # SHARD_INDEX is 1-based (matches Playwright + matrix values). qa-codegen config honors this.
      # Maestro job — include only if $GEN.maestro.enabled.
      # Two modes: cloud (preferred, requires MAESTRO_CLOUD_API_KEY) or local emulator.
      # Cloud mode:
      - name: Maestro cloud run
        if: ${{ false }}   # flip to true when $GEN.maestro.enabled
        uses: mobile-dev-inc/action-maestro-cloud@v1
        with:
          api-key: ${{ secrets.MAESTRO_CLOUD_API_KEY }}
          app-file: path/to/app.apk   # substitute actual $GEN.maestro.android_app_id build artifact
          workspace: qa/tests/mobile   # substitute actual $GEN.maestro.root

      # XCUI job — include only if $GEN.xcui.enabled. Runs on macOS.
      - name: XCUI tests
        if: ${{ false }}   # flip to true when $GEN.xcui.enabled; move to separate job with runs-on: macos-latest
        run: |
          xcodebuild test \
            -project qa/tests/ios/App.xcodeproj \
            -scheme AppUITests \
            -destination 'platform=iOS Simulator,name=iPhone 15,OS=latest' \
            -resultBundlePath qa/reports/xcui-result.xcresult

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          # Per-shard artifact name to avoid collisions across matrix jobs.
          name: qa-report-shard-${{ matrix.shard }}
          path: qa/reports/   # substitute actual $REPORTS value here
```

When writing the file: insert only the steps for enabled frameworks, using their actual `root` paths. **XCUI must run on a separate job with `runs-on: macos-latest`** — emit a second job block rather than inlining with Playwright/Maestro on ubuntu.

**XCUI job template** (separate job when `$GEN.xcui.enabled`):
```yaml
  xcui:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: maxim-lobanov/setup-xcode@v1
        with:
          xcode-version: latest-stable
      - name: Run XCUI tests
        run: |
          xcodebuild test \
            -project qa/tests/ios/App.xcodeproj \
            -scheme AppUITests \
            -destination 'platform=iOS Simulator,name=iPhone 15,OS=latest' \
            -resultBundlePath qa/reports/xcui-result.xcresult
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: xcui-report, path: qa/reports/xcui-result.xcresult }
```

**Maestro job template** (separate job when `$GEN.maestro.enabled`, cloud mode — preferred):
```yaml
  maestro:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # Build or download app artifact first (project-specific — left as TODO marker)
      - name: Maestro Cloud
        uses: mobile-dev-inc/action-maestro-cloud@v1
        with:
          api-key: ${{ secrets.MAESTRO_CLOUD_API_KEY }}
          app-file: ./app.apk
          workspace: qa/tests/mobile
```

**PR trigger** (`.github/workflows/qa-sync.yml`):
```yaml
name: QA Sync
on:
  pull_request:
    types: [closed]
    branches: [main]

jobs:
  sync:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          claude -p "/qa-sync --daily" --allowedTools Bash,Read,Write,Edit,Glob,Grep
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

**Auto-healer** (`.github/workflows/qa-heal.yml`):
```yaml
name: QA Auto-Healer
on:
  workflow_run:
    workflows: ["QA Full Suite"]
    types: [completed]

jobs:
  heal:
    if: github.event.workflow_run.conclusion == 'failure'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npx playwright install --with-deps
      - run: |
          claude -p "/qa-run" --allowedTools Bash,Read,Write,Edit,Glob,Grep
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          BASE_URL: ${{ vars.QA_BASE_URL }}
      # Surface heal fix as PR — skip if no changes.
      - name: Create heal PR
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          set -e
          if [ -z "$(git status --porcelain)" ]; then
            echo "No heal changes — exit."
            exit 0
          fi
          BRANCH="qa-heal/$(date +%Y%m%d-%H%M%S)"
          git config user.name "qa-heal-bot"
          git config user.email "qa-heal@users.noreply.github.com"
          git checkout -b "$BRANCH"
          git add -A qa/tests qa/reports
          git commit -m "fix(qa): auto-heal from run ${{ github.event.workflow_run.id }}"
          git push -u origin "$BRANCH"
          gh pr create \
            --title "qa-heal: auto-fix from failed run #${{ github.event.workflow_run.id }}" \
            --body "Automated heal pass. Review HEAL_FIX / HEAL_REVIEW tags in specs and qa/reports/heal-*.md before merge." \
            --base main --head "$BRANCH"
```

**Heal PR rules:**
- Never auto-merge. Human review required.
- Commit staged paths limited to `qa/tests` + `qa/reports` — never touch source code.
- Skip PR creation if `git status --porcelain` is empty (heal produced no changes).
- PR body must prompt reviewer to check `HEAL_REVIEW` tags (confidence < 0.70 fixes).

## Step 3 — Show Requirements

```
Installed: {list of files}

Required secrets (repo Settings → Secrets):
  ANTHROPIC_API_KEY
  MAESTRO_CLOUD_API_KEY   (only if gen.maestro.enabled + cloud mode)

Required variables (repo Settings → Variables):
  QA_BASE_URL — test environment URL

Heal PR permissions:
  Settings → Actions → General → Workflow permissions
  → "Read and write" + "Allow GitHub Actions to create and approve pull requests"
```

```bash
gh workflow list --repo $GITHUB_REPO
```

## Rules

- Never modify existing workflows — only add new files.
- ANTHROPIC_API_KEY only needed for CI workflows, not local runs.
- Adapt workflow YAML: skip playwright steps if only maestro enabled, etc.
