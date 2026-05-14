# qa-config.yml Field Reference

Full reference for `qa/qa-config.yml`. Required by all qabot skills.

## project

```yaml
project:
  name: ""              # project display name — used in reports and notifications
  github_repo: ""       # org/repo — used by qa-sync, qa-triage, qa-ci
  jira:
    url: ""             # https://myorg.atlassian.net
    project_key: ""     # PROJ — used for auto-linking, triage, and /qa-bug
    cloud_id: ""        # Atlassian cloud ID — find at: $JIRA_URL/_edge/tenant_info (required for /qa-bug)
    ready_for_qa_status: "Ready for QA"   # Jira status that signals ready for testing
```

## tc_format

```yaml
tc_format: B            # A | B | C (default: B)
```

Controls TC verbosity for /qa-plan output. See `docs/TC-SCHEMA.md` for format examples.

| Value | Description |
|-------|-------------|
| `A` | Title + expected result only. Steps omitted. |
| `B` | Single prose step block + expected result. Default. |
| `C` | Verbose: per-step with individual expected results. |

## tc_id

```yaml
tc_id:
  format: "TC-{DOM}-{X}.{Y}.{Z}"   # ID format template
  domains:                           # domain key → abbreviation map
    web: WEB
    mobile: MOB
    backend: BE
    non_functional: NF
```

`{DOM}` resolves from the TC's `platform` field via this map. Add custom domains here; they must match `platform` values used in TCs.

## paths

```yaml
paths:
  cases: qa/cases         # TC YAML files
  docs: qa/docs           # source docs for planning
  tests: qa/tests         # generated test specs
  sync_log: qa/sync-log.md
  reports: qa/reports     # run reports, analysis, heal logs
```

## gen (framework blocks)

Each framework block: `enabled: false` by default. Enable before running /qa-codegen.

```yaml
gen:
  playwright:
    enabled: false
    root: qa/tests/web
    base_url: ""            # http://localhost:3000 — used for qa-run and qa-explore
    shards: 1               # CI matrix fan-out
    workers: 1              # local parallel workers per shard

  maestro:
    enabled: false
    root: qa/tests/mobile
    android_app_id: ""      # com.example.app
    ios_app_id: ""          # com.example.app

  xcui:
    enabled: false
    root: qa/tests/ios
    scheme: ""              # Xcode scheme name

  api:
    enabled: false
    root: qa/tests/api
    framework: supertest    # supertest | pytest | rest-assured
    base_url: ""

  a11y:
    enabled: false
    root: qa/tests/a11y
    wcag_level: AA          # A | AA | AAA

  vrt:
    enabled: false
    root: qa/tests/vrt
    threshold: 0.2          # max pixel diff ratio (0.0–1.0)
    update_baselines: false

  performance:
    enabled: false
    root: qa/tests/perf
    framework: lighthouse   # lighthouse | k6
    budget_json: ""         # path to budgets.json / k6 thresholds file

  security:
    enabled: false
    root: qa/tests/security
    framework: zap          # zap | nuclei
    target_url: ""          # scan target; falls back to gen.playwright.base_url

  espresso:
    enabled: false
    root: qa/tests/android
    package: ""             # com.example.app
```

## adversarial

```yaml
adversarial:
  base_url: ""            # sandbox URL only — never production
```

Required for /qa-adversarial. Must differ from `gen.playwright.base_url`.

## reports

```yaml
reports:
  retention_days: 30      # prune qa/reports/ older than N days on each /qa-run (0 = keep forever)
```

## notifications

```yaml
notifications:
  slack_webhook: ""       # https://hooks.slack.com/... — posts /qa-run summary + /qa-sync PR URL
  teams_webhook: ""       # https://outlook.office.com/webhook/...
```

## testrail

```yaml
testrail:
  enabled: false
  url: ""                 # https://acme.testrail.io
  project_id: 0           # numeric
  suite_id: 0             # optional; 0 for single-suite projects
```

Auth lives in a local `.env` (never committed): `TR_USER`, `TR_API_KEY`, `TR_PASSWORD`.

## models

```yaml
models:
  default: claude-sonnet-4-6
  planner: ""             # empty = falls back to default
  validator: ""           # empty = falls back to default
  codegen: ""
  run_analysis: ""
  heal: ""
  sync: ""
```

---

## Runtime Environment Variables

Set by the `/qa` orchestrator at session start. Sub-skills read these — do not set manually.

| Variable | Set by | Description |
|----------|--------|-------------|
| `QABOT_SESSION` | `/qa` | 8-char hex session ID. Shared across all phase reports for correlation |
| `QABOT_SCOPE` | `/qa` | Comma-separated domain abbreviations or `all`. Limits which TCs are in scope |
| `QABOT_FRAMEWORK` | `/qa` | Framework config key (`playwright`, `maestro`, etc.) or `all` |
| `QABOT_TC_IMMUTABLE` | `/qa`, `/qa-codegen` | `1` = hook blocks writes to immutable TC fields |
| `QABOT_AGENT_ROLE` | `/qa-codegen` | `agent-a` or `agent-b` — enforces information barrier in hook |
| `RTK_ENABLED` | `/qa` | `1` = RTK wrapping active for doc reads, test runs, PR fetch |
| `TC_FORMAT` | `/qa` | Resolved from `tc_format` in config (`A`, `B`, or `C`) |

---

## Prompt-Injected Static Config Block

The `/qa` orchestrator resolves config once and injects this block into all sub-skill spawns. Sub-skills never re-read `qa-config.yml` directly.

```yaml
# Injected by orchestrator — do not edit manually
project: {name}
paths: {cases, docs, tests, reports, sync_log}
tc_id: {format, domains}
tc_format: {A|B|C}
gen: {per-framework blocks}
models: {per-role overrides}
jira: {url, project_key, ready_for_qa_status}
adversarial: {base_url}
testrail: {enabled, url, project_id, suite_id}
notifications: {slack_webhook, teams_webhook}
reports: {retention_days}
```
