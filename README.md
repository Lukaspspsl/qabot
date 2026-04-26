# qabot

QA framework for Claude Code. One config file, approval gates between every phase, minimal console output. Designed for token efficiency — main context never reads test cases or specs directly.

## Install (Claude Code Plugin)

Add the marketplace, then install:

```bash
/plugin marketplace add Lukaspspsl/qabot
/plugin install qabot@qabot
```

Pin a release:

```bash
/plugin install qabot@qabot@v0.1.0
```

After install, `/qa` and all sub-skills (`/qa-plan`, `/qa-codegen`, `/qa-run`, `/qa-sync`, `/qa-triage`, `/qa-ci`, `/qa-explore`, `/qa-adversarial`, `/qa-init`) are available in any project.

### Hook configuration (optional)

The bundled `pre_tool_use.py` hook reads block patterns from env. All optional:

| Var | Purpose | Example |
|-----|---------|---------|
| `QABOT_BLOCKED_URLS` | Comma-separated regex; block WebFetch/curl to these URLs | `https?://api\.acme\.com,https?://.*\.prod\.` |
| `QABOT_BLOCKED_BASH` | Comma-separated regex; override default destructive-bash blocklist | `rm\s+-rf\s+/,DROP\s+TABLE` |
| `QABOT_WORKSPACE` | Absolute path; warn on writes outside this root | `/Users/me/proj/qa` |
| `QABOT_AGENT_ROLE` | `A` or `B`; enforces info-barrier during codegen | `A` |

### Telemetry (off by default)

`hooks/send_event.py` exists for opt-in observability but is **not wired** in `hooks/hooks.json`. To enable:

1. Run a local obs server (defaults to `http://localhost:4000`); override with `OBS_SERVER_URL`.
2. Add a `PostToolUse` entry calling `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/send_event.py --event-type tool_use` in `hooks/hooks.json`.

No telemetry is collected unless you opt in.

## Quick Start

```bash
# 1. Scaffold — creates qa/ layout, .env.example, extensive .gitignore
/qa-init

# 2. Fill in qa/qa-config.yml:
#    - project.name, project.github_repo, project.jira.*
#    - enable at least one framework under gen.*
# 3. Place source docs in qa/docs/

# 4. Run
/qa
```

Everything qa-related nests under `qa/` in your project. Only `qa/cases/`, `qa/tests/`, `qa/qa-config.yml`, `qa/sync-log.md`, `qa/templates/` are committed by default — reports, .env, discovery artifacts, and testrail state are local-only.

The orchestrator checks prerequisites, shows pipeline status, and routes you to the right phase automatically. If `qa/qa-config.yml` is missing, `/qa` auto-routes to `/qa-init`.

## How to Use

### First Run

Copy `templates/qa-config.yml` to your project root. Fill in the required fields:

```yaml
project:
  name: "My App"
  github_repo: "org/repo"
  jira:
    url: "https://org.atlassian.net"
    project_key: "PROJ"

gen:
  playwright:
    enabled: true
    base_url: "http://localhost:3000"
```

Run `/qa` — it auto-routes to `/qa-plan` if no test cases exist yet.

### Phase Flow

```
/qa-explore  →  /qa-plan  →  /qa-codegen  →  /qa-run  →  /qa-adversarial
   0.5             1              2               3             2.5
(optional)                                              (optional, post-run)

/qa-sync (after each release cycle)
/qa-triage (before each QA cycle)
/qa-ci (one-time setup)
```

Each phase shows a gate before proceeding. Use `[f] full run` from the menu to chain Plan → Codegen → Run with a single confirmation per step.

### Skills Reference

| Skill | Phase | What it does |
|-------|-------|--------------|
| `/qa` | — | Orchestrator — prereq checks, status, routing |
| `/qa-init` | — | One-time scaffold — creates `qa/` dirs, copies config, writes `.gitignore` |
| `/qa-explore` | 0.5 | Browser-based live app discovery before planning |
| `/qa-plan` | 1 | Generate TCs via Planner + Validator agent loop |
| `/qa-codegen` | 2 | Generate Playwright / Maestro / XCUI automation |
| `/qa-run` | 3 | Execute tests, analyse failures, auto-heal |
| `/qa-adversarial` | 2.5 | Edge-case battery against isolated sandbox |
| `/qa-sync` | 4 | PR sync — new TCs for changed features |
| `/qa-sync --daily` | 4 | Auto-approve covered PRs, open review PR |
| `/qa-triage` | — | Score Jira tickets against release signals |
| `/qa-ci` | — | Write GitHub Actions workflow files |
| `/qa-testrail` | 4 | Optional — push TCs to TestRail (requires `testrail.enabled` + `.env` creds) |
| `/qa-bug` | post-run | File failures from run-analysis / adversarial draft as Jira or GitHub issues |
| `/qa-coverage` | — | Regenerate `qa/TEST-COVERAGE.md` — TC counts, automation %, gap list |
| `/qa-retire` | — | Mark TCs `deprecated: true` for removed features (PR scan or manual) |

---

## Architecture

### Config Contract

`qa-config.yml` is read **once** by the `/qa` orchestrator. All resolved values are passed inline to sub-skills — sub-skills never re-read the file.

Key config sections:

| Section | Purpose |
|---------|---------|
| `project` | Name, GitHub repo, Jira connection |
| `tc_id` | TC ID format and domain abbreviations |
| `paths` | Where cases, docs, tests, reports live |
| `gen.*` | Per-framework enable flags + settings |
| `adversarial` | Sandbox URL for edge-case testing |
| `models` | Per-role model overrides (all fall back to `models.default`) |

### TC ID Format

Configurable via `tc_id.format` (default: `TC-{DOM}-{X}.{Y}.{Z}`).

- `{DOM}` — domain abbreviation from `tc_id.domains` (WEB / MOB / BE / NF)
- `{X}.{Y}.{Z}` — feature group . sub-feature . case number

**IDs are immutable after first write.** Only `jira_key`, `automation_id`, `automation_status` may be updated on existing TCs.

### TC Schema (canonical)

`templates/tc.yml` is the single source of truth. All qa-* skills (qa-plan, qa-sync, qa-adversarial, qa-codegen, qa-testrail) read/write TCs conforming to this schema. `automation_status` defaults to `manual` on new TCs; `/qa-codegen` flips it to `automated` and backfills `automation_id`.

### Agent Patterns

**Planner + Validator loop** (`/qa-plan`):
Planner agent writes TCs. Validator agent checks quality against a strict checklist. Max 2 iterations — if issues remain after iteration 2, user decides.

**Info Barrier** (`/qa-codegen`):
- Agent A receives TC YAMLs with `expected_result` redacted → writes test code with `ASSERT_HERE` markers
- Main context builds `{ TC_ID → expected_result }` lookup map in memory only
- Agent B receives only the lookup map → fills in assertions

This prevents Agent A from writing tests that simply mirror the expected result, preserving assertion independence.

**Heal subagent** (`/qa-run`):
Fixes broken locators, timing issues, navigation errors. Tags every change with `HEAL_FIX: [reason] | confidence: X.XX`. Changes with confidence < 0.70 tagged `HEAL_REVIEW` and surfaced to user before re-run.

### Sub-skill Contracts

Each skill receives a defined set of variables from the orchestrator and returns a summary (never raw file contents). Main context only ever sees counts and paths — never TC bodies or spec code.

| Skill | Receives | Returns |
|-------|----------|---------|
| qa-plan | $CASES, $DOCS, $MODELS, $TC_FORMAT, $TC_DOMAINS, $JIRA_URL, $JIRA_KEY, $DISCOVERY_REPORT? | TC count, CSV path |
| qa-codegen | $CASES, $TESTS, $MODELS, $TC_FORMAT, $GEN | spec count per framework, skipped TC IDs |
| qa-run | $TESTS, $REPORTS, $MODELS, $GEN, $BASE_URL | pass rate per framework, fail count, HEAL_REVIEW count |
| qa-sync | $CASES, $DOCS, $TESTS, $SYNC_LOG, $MODELS, $TC_FORMAT, $TC_DOMAINS, $GITHUB_REPO, $JIRA_URL, $JIRA_KEY, $GEN | new TC count, sync log path |
| qa-explore | $GEN, $DOCS | $DISCOVERY_REPORT path or empty |
| qa-adversarial | $ADV_URL, $CASES, $REPORTS, $TC_FORMAT, $TC_DOMAINS | draft TC count |
| qa-triage | $CASES, $GITHUB_REPO, $JIRA_URL, $JIRA_KEY, $JIRA_QA_STATUS, $MODELS | (ephemeral — no files written) |
| qa-ci | $GITHUB_REPO, $GEN, $TESTS, $REPORTS | workflow file paths |
| qa-testrail | $CASES, $TC_FORMAT, $TC_DOMAINS, $TESTRAIL.*, $SYNC_LOG | created/updated counts |
| qa-bug | $REPORTS, $CASES, $GITHUB_REPO, $JIRA_URL, $JIRA_KEY, $MODELS | filed count per destination |
| qa-coverage | $CASES, $DOCS, $TESTS, $MODELS, $GEN | coverage md path, totals |
| qa-retire | $CASES, $TESTS, $SYNC_LOG, $GITHUB_REPO, $MODELS, $GEN | retired count, report path |

### Output Structure

```
<project-root>/
├── qa-config.yml
├── qa/
│   ├── cases/
│   │   ├── <feature-group>/
│   │   │   └── TC-WEB-1.1.1-short-title.yml
│   │   └── test-plan.csv
│   ├── docs/            # source docs for planning
│   ├── reports/         # run-analysis-*.md, heal-*.md, results-*.json
│   └── sync-log.md
├── qa/tests/
│   ├── web/             # Playwright (pages/, specs/, fixtures/, data/)
│   ├── mobile/          # Maestro (suites/, flows/, subflows/, data/)
│   └── ios/             # XCUI (Pages/, Tests/, Helpers/, Data/)
└── .context/            # ephemeral — explore + adversarial artifacts
```

### Jira Integration

If `project.jira.project_key` is set, a subagent attempts to link each new TC to a matching Jira ticket by keyword search after every `/qa-plan` or `/qa-sync` run. Match threshold: >80% title keyword overlap. Ambiguous or failed matches are left empty — never blocked on Jira availability.

`/qa-triage` also uses Jira (via Atlassian MCP) to score in-flight tickets against release signals before a QA cycle. Paste fallback available if MCP is unavailable.

### Adding a New Automation Framework

1. Add `gen.<name>:` block to `templates/qa-config.yml` with `enabled`, `root`, and framework-specific fields
2. Add `## Framework: <Name>` section to `skills/qa-codegen/SKILL.md` — skip condition, file structure, element/locator rules, `ASSERT_HERE` marker syntax
3. Add run command + heal block to `skills/qa-run/SKILL.md`
4. The info barrier pattern, TC backfill, and immutability rules all apply unchanged

### TBD — Issue #12: Explore and Adversarial Agent Types

`/qa-explore` spawns a browser-based discovery agent. `/qa-adversarial` spawns an adversarial UI testing agent. The exact agent type identifiers for these sub-skills are **TBD** — current SKILL.md files reference `web-app-auditor` and `ui-adversarial` respectively, but the correct subagent_type values for the Agent tool in this runtime context have not been confirmed. Validate before relying on these phases in production use.
