# qabot — Architecture

Lightweight QA framework. Main context never reads TC bodies or spec code — only counts and paths. All heavy work happens inside subagents.

## Phase Graph

```
           ┌─────────────┐
           │  /qa-init   │  (one-time scaffold — writes qa/qa-config.yml, dirs, .gitignore)
           └──────┬──────┘
                  ▼
           ┌─────────────┐
           │    /qa      │  orchestrator — doctor checks, session ID, routes by state
           └──────┬──────┘
                  ▼
  0.5  /qa-explore  (optional — live app discovery, web-app-auditor agent)
   │
   ▼
  1    /qa-plan       → TCs in qa/cases/**.yml + qa/test-plan.csv + plan-{session}.md
   │
   ▼
  2    /qa-codegen    → Playwright / Maestro / XCUI specs + codegen-{framework}-{session}.md
   │
   ▼
  3    /qa-run        → execute + analyse + heal; run-analysis-{framework}-{session}.md
   │
   ▼
  2.5  /qa-adversarial  (optional, post-run — ui-adversarial agent, sandbox only)
   │
   ▼
  4    /qa-testrail   (optional — push to TestRail)
       /qa-sync       (on each release — scan merged PRs, add new TCs)
       /qa-triage     (before QA cycle — score Jira tickets)
       /qa-ci         (one-time — write GitHub Actions workflows)
       /qa-bug        (failure → Jira/GitHub issue)
```

Each phase has a human approval gate before the next runs. `[f] full run` from the menu chains Plan → Codegen → Run with one confirmation per step.

## Session ID

`/qa` generates an 8-char hex session ID (`QABOT_SESSION`) at startup via `openssl rand -hex 4`. All reports from that session share the same ID for correlation:

```
qa/reports/plan-{session}.md
qa/reports/codegen-{framework}-{session}.md
qa/reports/run-analysis-{framework}-{session}.md
qa/reports/run-output-{framework}-{session}.txt
qa/reports/heal-{framework}-{session}.md
qa/reports/sync-{session}.md
```

Framework names in report filenames = config keys: `playwright`, `maestro`, `xcui`, `api`, `a11y`, `vrt`, `performance`, `security`, `espresso`. Never aliases like `web` or `mobile`.

## Core Patterns

### Doctor Checks

`/qa` runs tiered checks before each session:

**Hard-fail (stop pipeline):**
- `which rtk` — RTK required for token efficiency
- `ANTHROPIC_API_KEY` set — required to spawn agents
- `qa/qa-config.yml` exists and valid
- `.claude/hooks/pre_tool_use.py` installed

**Warn (ask to continue):**
- `gh auth status` — needed for qa-sync/qa-ci
- Jira MCP reachable — needed for auto-link + triage
- TestRail creds in `.env` — needed for qa-testrail
- Obs server running at localhost:4000

### RTK Integration

RTK (Rust Token Killer) wraps three operations for 60–90% token savings:

```bash
rtk read {doc_file}                    # qa-plan doc injection
rtk test "npx playwright test ..."     # qa-run test execution
rtk gh pr list --json ...              # qa-sync PR fetch
```

RTK is a mandatory dependency. `/qa` hard-fails if `which rtk` returns nothing.

### Builder-Validator

Two-agent loop used in `/qa-plan`.

- **Builder (Planner)** — writes all TC YAMLs from source docs.
- **Validator** — independent agent checks output against strict schema + quality checklist. Returns `APPROVED` or `ISSUES: [...]`.
- Max 2 iterations. Third pass would mean the builder can't learn — surface issues to user instead.

Validator gets only the written files, never the builder's reasoning.

### Information Barrier (`/qa-codegen`)

Prevents tests from mirroring their own expected results:

1. **Main context** reads all TCs, builds `{ TC_ID → expected_result }` map in memory. Substitutes `"REDACTED"` for `expected_result` in every TC copy — this is string substitution, not an instruction.
2. **Agent A** receives TC copies with `expected_result = "REDACTED"`. Writes test code with `# ASSERT_HERE: {TC_ID}` markers.
3. **Post-write leak check** — main context greps each written file for substrings (≥6 chars) from original expected_result values. Hit = Agent A leaked. Reject + retry (max 2).
4. **Agent B** receives only the plain text lookup map (no spec paths, no `qa/cases/` access). Replaces each `ASSERT_HERE` marker with a real assertion.

Consequence: Agent A cannot copy expected results into tests. Agent B cannot see test logic.

### Immutability

Once a TC YAML is written, these fields are **immutable**:

`schema_version`, `id`, `title`, `steps`, `expected_result`, `preconditions`, `type`, `platform`, `priority`, `source_docs`

Only these may be updated on existing TCs:

- `jira_key` — auto-link backfill
- `automation_id` — codegen backfill (YAML map keyed by framework)
- `automation_status` — `manual` → `automated` after codegen
- `deprecated` — retire flow; never deletes

`pre_tool_use.py` hook enforces this when `QABOT_TC_IMMUTABLE=1` is set.

### TC Verbosity

Three formats, controlled by `tc_format` in `qa-config.yml` (default: `B`):

| Format | Steps | expected_result |
|--------|-------|-----------------|
| A | omitted | single outcome |
| B | single prose block | single outcome |
| C | list with `{step, expected}` per item | overall outcome |

### automation_id Format

YAML map keyed by framework config key. Never a string or comma-separated value:

```yaml
automation_id:
  playwright: qa/tests/web/specs/auth/tc-web-1-1-1.spec.ts
  maestro: qa/tests/mobile/flows/tc-mob-1-1-1.yaml
```

Multi-framework runs add keys without overwriting existing ones.

### Config Contract

`qa-config.yml` is read **once** by `/qa`. All resolved values are passed inline to sub-skills. Sub-skills never re-read the config file.

### Coverage Tally

Coverage is computed inline by the orchestrator after each run — no subagent spawn:

```bash
find "$CASES" -name "*.yml" | xargs grep -l "schema_version"  # total
grep -rl "platform: web" "$CASES" --include="*.yml"           # WEB
grep -rl "automation_status: automated" "$CASES" ...          # automated
```

Output: `Coverage: {N} TCs — WEB:{w} MOB:{m} BE:{b} NF:{n} | Automated: {a}%`

## Consumer Project Layout

```
<project-root>/
├── .gitignore               # qa-init writes qa-specific ignore rules here
└── qa/
    ├── qa-config.yml        # single config, read once by /qa
    ├── cases/               # TC YAMLs — committed
    ├── tests/               # specs/flows — committed
    ├── docs/                # source docs — local by default
    ├── reports/             # run analysis, heal logs — local
    ├── templates/           # local copy of tc.yml for reference
    ├── sync-log.md          # committed; tracks last_sync date
    ├── .context/            # ephemeral discovery + adversarial artifacts
    ├── .trsync/             # testrail mapping.json (per-clone state)
    ├── .env                 # TestRail / API creds — never committed
    └── .env.example         # committed template
```

**Committed by default:** `qa/cases/**`, `qa/tests/**`, `qa/qa-config.yml`, `qa/sync-log.md`, `qa/templates/`, `qa/.env.example`.

**Everything else local.** Reports, discovery artifacts, mapping state, source docs, framework outputs.

## Non-obvious Invariants

- **Never** modify existing TC YAML fields except the allow-list above.
- **Never** delete TCs — use `deprecated: true`.
- **Never** push or auto-merge from a skill — PRs only.
- **Never** block on Jira unavailability — auto-link is best-effort.
- **Never** test adversarially against a dev server — `adversarial.base_url` must differ from `gen.playwright.base_url`.
- **Never** leak TC expected results into Agent A's codegen context.
- **Never** use framework aliases (`web`/`mobile`) in report names — always config key (`playwright`/`maestro`).

## Sub-skill Contracts

| Skill | Receives | Returns |
|-------|----------|---------|
| qa-plan | $CASES, $DOCS, $MODELS, $TC_FORMAT, $TC_DOMAINS, $TC_VERBOSITY, $JIRA_URL, $JIRA_KEY, $QABOT_SESSION, $QABOT_SCOPE, $DISCOVERY_REPORT? | TC count, CSV path, report path |
| qa-codegen | $CASES, $TESTS, $MODELS, $TC_FORMAT, $GEN, $QABOT_SESSION, $QABOT_FRAMEWORK | spec count per framework, backfill count, skipped IDs, report paths |
| qa-run | $TESTS, $REPORTS, $MODELS, $GEN, $BASE_URL, $QABOT_SESSION, $QABOT_FRAMEWORK | pass rate per framework, fail count, HEAL_REVIEW count, report paths |
| qa-sync | $CASES, $DOCS, $TESTS, $SYNC_LOG, $MODELS, $TC_FORMAT, $TC_DOMAINS, $GITHUB_REPO, $JIRA_URL, $JIRA_KEY, $GEN, $QABOT_SESSION | new TC count, report path |
| qa-explore | $GEN, $DOCS | $DISCOVERY_REPORT path or empty |
| qa-adversarial | $ADV_URL, $CASES, $REPORTS, $TC_FORMAT, $TC_DOMAINS, $QABOT_SESSION | draft TC count |
| qa-triage | $CASES, $GITHUB_REPO, $JIRA_URL, $JIRA_KEY, $JIRA_QA_STATUS, $MODELS | (ephemeral) |
| qa-ci | $GITHUB_REPO, $GEN, $TESTS, $REPORTS | workflow file paths |
| qa-testrail | $CASES, $TC_FORMAT, $TC_DOMAINS, $TESTRAIL.*, $SYNC_LOG | created/updated counts |
| qa-bug | $REPORTS, $CASES, $GITHUB_REPO, $JIRA_URL, $JIRA_KEY, $MODELS | filed count per destination |
| qa-retire | $CASES, $TESTS, $SYNC_LOG, $GITHUB_REPO, $MODELS, $GEN | retired count, report path |

## Adding a Framework

1. Add `gen.<name>:` block to `templates/qa-config.yml`.
2. Add `## Framework: <Name>` section to `skills/qa-codegen/SKILL.md`.
3. Add run command block to `skills/qa-run/SKILL.md`.
4. Info barrier, TC backfill, immutability, and RTK wrapping all apply unchanged.
