# qabot

QA framework for Claude Code covering all the stages from analysis and plan, to test case generation, automation scripting and runner. One config file, approval gates between every phase, minimal console output.

## Install

Clone the repo, bootstrap `/qa-init`, then let it distribute the rest:

```bash
# 1. Clone qabot somewhere permanent (e.g. ~/qabot)
git clone https://github.com/Lukaspspsl/qabot.git

# 2. Bootstrap — copy only qa-init so it's available as a skill
cp -r ~/qabot/skills/qa-init ~/.claude/skills/
```

Then, in your target project, run Claude and use init skill:

```
/qa-init
```

`/qa-init` will copy all remaining skills to `~/.claude/skills/`, optionally wire the hooks, and scaffold your project's `qa/` directory. All subsequent projects only need step 3 — skills are already global.

Pin a release:

```bash
git clone --branch v0.1.0 https://github.com/Lukaspspsl/qabot.git ~/.qabot
```

After install, `/qa` and all sub-skills (`/qa-plan`, `/qa-codegen`, `/qa-run`, `/qa-sync`, `/qa-triage`, `/qa-ci`, `/qa-explore`, `/qa-adversarial`, `/qa-bug`, `/qa-retire`, `/qa-testrail`, `/qa-init`) are available in any project.

**Prerequisites:** RTK (Rust Token Killer) is required. Install from https://github.com/rtk-ai/rtk before using qabot. `/qa` will hard-fail without it.

### Hook configuration (optional)

The bundled `pre_tool_use.py` hook reads block patterns from env. All optional:

| Var | Purpose | Example |
|-----|---------|---------|
| `QABOT_BLOCKED_URLS` | Comma-separated regex; block WebFetch/curl to these URLs | `https?://api\.acme\.com,https?://.*\.prod\.` |
| `QABOT_BLOCKED_BASH` | Comma-separated regex; override default destructive-bash blocklist | `rm\s+-rf\s+/,DROP\s+TABLE` |
| `QABOT_WORKSPACE` | Absolute path; warn on writes outside this root | `/Users/me/proj/qa` |
| `QABOT_AGENT_ROLE` | `agent-a` or `agent-b`; enforces info-barrier during codegen | `agent-a` |

### Observability layer (off by default)

`hooks/send_event.py` exists for opt-in observability but is **not wired** in `hooks/hooks.json`. To enable:

1. Run a local obs server (defaults to `http://localhost:4000`); override with `OBS_SERVER_URL`.
2. Add a `PostToolUse` entry calling `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/send_event.py --event-type tool_use` in `hooks/hooks.json`.


## How to Use

Everything qa-related nests under `qa/` in your project. Only `qa/cases/`, `qa/tests/`, `qa/qa-config.yml`, `qa/sync-log.md`, `qa/templates/` are committed by default — reports, .env, discovery artifacts, and testrail state are local-only.

The orchestrator checks prerequisites, shows pipeline status, and routes you to the right phase automatically. If `qa/qa-config.yml` is missing, `/qa` auto-routes to `/qa-init`.

### First Run

After `/qa-init` scaffolds your project, fill in `qa/qa-config.yml`:

```yaml
project:
  name: "My App"
  github_repo: "org/repo"
  jira:
    url: "https://org.atlassian.net"
    project_key: "PROJ"

tc_format: B               # A=title+result only, B=single step block (default), C=verbose per-step

gen:
  playwright:
    enabled: true
    base_url: "http://localhost:3000"
```

Run `/qa` — it auto-routes to `/qa-plan` if no test cases exist yet.

`/qa` is main orchestrator, use it to run dedicated skills.

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
| `/qa-init` | — | Bootstrap + scaffold — `--from <path>` distributes skills globally on first install; always creates `qa/` dirs, copies config, writes `.gitignore` |
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
| `/qa-retire` | — | Mark TCs `deprecated: true` for removed features (PR scan or manual) |

---

## Architecture

See `docs/ARCHITECTURE.md` for full details. Key points:

- `qa-config.yml` is read **once** by `/qa`. All resolved values passed inline to sub-skills.
- Session ID (`QABOT_SESSION`) generated at startup — all reports from a session share the same ID.
- RTK wraps doc reads, test execution, and PR fetching for 60–90% token savings.
- Coverage tally computed inline by orchestrator — no subagent.

### TC Schema (canonical)

`templates/tc.yml` + `docs/TC-SCHEMA.md`. Key fields:

- `schema_version: 1`
- `id: TC-{DOM}-{X}.{Y}.{Z}` — domain from `tc_id.domains`, immutable after write
- `automation_id` — YAML map keyed by framework config key (e.g. `playwright:`, `maestro:`)
- `tc_format` in config controls verbosity: A (title+result), B (single step block, default), C (verbose per-step)

### Agent Patterns

**Planner + Validator loop** (`/qa-plan`):
Planner agent writes TCs from RTK-injected docs. Validator checks quality + schema. Max 2 iterations.

**Info Barrier** (`/qa-codegen`):
- Main context replaces `expected_result` with `"REDACTED"` (string substitution) before Agent A spawn
- Agent A writes test code with `# ASSERT_HERE: {TC_ID}` markers
- Post-write leak check: grep for expected_result substrings in written files — hit = reject + retry
- Agent B receives only the `TC_ID → expected_result` plain text map — fills assertions

**Heal subagent** (`/qa-run`):
Fixes broken locators, timing, navigation. Tags changes with confidence score. `HEAL_REVIEW` for <0.70.

### Output Structure

```
<project-root>/
└── qa/
    ├── qa-config.yml    # single config, read once by /qa
    ├── cases/
    │   ├── <feature-group>/
    │   │   └── TC-WEB-1.1.1-short-title.yml
    │   └── test-plan.csv
    ├── docs/            # source docs for planning
    ├── reports/         # plan-{session}.md, codegen-{fw}-{session}.md, run-analysis-{fw}-{session}.md
    ├── sync-log.md
    ├── tests/
    │   ├── web/         # Playwright
    │   ├── mobile/      # Maestro
    │   └── ios/         # XCUI
    ├── .context/        # explore + adversarial artifacts
    └── .env             # creds — never committed
```

### Adding a New Framework

1. Add `gen.<name>:` block to `templates/qa-config.yml`
2. Add `## Framework: <Name>` section to `skills/qa-codegen/SKILL.md`
3. Add run command block to `skills/qa-run/SKILL.md`
4. Info barrier, TC backfill, RTK wrapping, immutability all apply unchanged
