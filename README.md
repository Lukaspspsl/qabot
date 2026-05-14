# qabot

QA framework for Claude Code covering software testing stages from analysis and plan, to test case generation, automation scripting and runner. One config file, human approval gates between every phase. Vibed and always under construction.

**At the moment it requires Rust Token Killer** — a CLI proxy that compresses tool output for 60–90% token savings. Install from https://github.com/rtk-ai/rtk before using qabot. `/qa` will hard-fail without it.
(may change later)

## Install

```bash
npx qabot-cli init
```

Run in your target project root directory. Installs skills into `.claude/skills/`, hooks into `.claude/hooks/`, wires `.claude/settings.json`, and scaffolds `qa/` folder.

Skills and hooks are **project-local and git-ignored** — each developer runs `npx qabot-cli init` once per project clone. Hook wiring (`.claude/settings.json`) is committed so teammates get it automatically.

## How to Use

Everything qa-related nests under `qa/` in your project. Open Claude Code and run `/qa` to invoke master orchestrator skill — it checks prerequisites, shows pipeline status, and routes you to the right phase automatically. If `qa/qa-config.yml` is missing, `/qa` auto-routes to `/qa-init`.

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
| `/qa-init` | — | Re-scaffold `qa/` dirs, config, .gitignore (skills + hooks installed by `npx qabot-cli init`) |
| `/qa-explore` | 0.5 | Browser-based live app discovery before planning |
| `/qa-plan` | 1 | Generate TCs via Planner + Validator agent loop |
| `/qa-live` | 1.5 | Buddy for live manual debug session |
| `/qa-codegen` | 2 | Generate Playwright / Maestro / XCUI automation |
| `/qa-run` | 3 | Execute tests, analyse failures, auto-heal |
| `/qa-adversarial` | 2.5 | Edge-case battery against isolated sandbox - TBD!! |
| `/qa-sync` | 4 | PR sync — new TCs for changed features |
| `/qa-sync --daily` | 4 | Auto-approve covered PRs, open review PR |
| `/qa-triage` | — | Score Jira tickets against release signals |
| `/qa-ci` | — | Write GitHub Actions workflow files - TBD!! |
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

Framework is set so that the test case ID is immutable and ideally carries through the whole process. This way it should be free of friction and conflict.

`templates/tc.yml` + `docs/TC-SCHEMA.md`. Key fields:

- `schema_version: 1`
- `id: TC-{DOM}-{X}.{Y}.{Z}` — domain from `tc_id.domains`, immutable after write
- `automation_id` — YAML map keyed by framework config key (e.g. `playwright:`, `maestro:`)
- `tc_format` in config controls verbosity: A (title+result), B (single step block, default), C (verbose per-step)

### Agent Patterns

**Planner + Validator loop** (`/qa-plan`):
Planner agent writes TCs from RTK-injected docs. Validator checks quality (based on skill wording) + schema. Max 2 iterations.

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
├── .claude/
│   ├── settings.json    # hook wiring — committed
│   ├── skills/qa*/      # qabot skills — git-ignored, reinstall via --from
│   └── hooks/           # qabot hooks — git-ignored, reinstall via --from
└── qa/
    ├── tests/           # automation scripts — committed by default
    │   ├── web/         # Playwright
    │   ├── mobile/      # Maestro
    │   └── ios/         # XCUI
    ├── qa-config.yml    # git-ignored by default
    ├── cases/           # TC YAMLs — git-ignored by default
    ├── docs/            # source docs for planning — git-ignored by default
    ├── reports/         # plan/codegen/run-analysis reports — git-ignored by default
    ├── sync-log.md      # sync state — git-ignored by default
    ├── .context/        # explore + adversarial artifacts — git-ignored by default
    └── .env             # creds, never committed
```

Only `qa/tests/` is committed by default. Everything else under `qa/` is git-ignored. To commit cases, config, docs, or reports, remove the relevant lines from `.gitignore`.

### Hook Configuration

The bundled `pre_tool_use.py` hook enforces the Agent A/B info barrier and blocks destructive patterns. It reads optional env vars:

| Var | Purpose | Example |
|-----|---------|---------|
| `QABOT_BLOCKED_URLS` | Comma-separated regex; block WebFetch/curl to these URLs so you avoid prod env. | `https?://api\.acme\.com,https?://.*\.prod\.` |
| `QABOT_BLOCKED_BASH` | Comma-separated regex; override default destructive-bash blocklist | `rm\s+-rf\s+/,DROP\s+TABLE` |
| `QABOT_WORKSPACE` | Absolute path; warn on writes outside this root | `/Users/me/proj/qa` |
| `QABOT_AGENT_ROLE` | `agent-a` or `agent-b`; enforces info-barrier during codegen | `agent-a` |

### Observability Layer (off by default)

`hooks/send_event.py` exists for opt-in observability but is **not wired** by default. To enable:

1. Run a local obs server (script in folder `/obs/start-obs.sh` - it defaults to `http://localhost:4000`); override with `OBS_SERVER_URL`.
2. Add a `PostToolUse` entry calling `python3 .claude/hooks/send_event.py --event-type tool_use` in `.claude/settings.json`.

### Adding a New Automation Framework

1. Add `gen.<name>:` block to `templates/qa-config.yml`
2. Add `## Framework: <Name>` section to `skills/qa-codegen/SKILL.md`
3. Add run command block to `skills/qa-run/SKILL.md`
4. Info barrier, TC backfill, RTK wrapping, immutability all apply unchanged
