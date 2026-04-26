# qa-concise — Architecture

Lightweight QA framework. Main context never reads TC bodies or spec code — only counts and paths. All heavy work happens inside subagents.

## Phase Graph

```
           ┌─────────────┐
           │  /qa-init   │  (one-time scaffold — writes qa/qa-config.yml, dirs, .gitignore)
           └──────┬──────┘
                  ▼
           ┌─────────────┐
           │    /qa      │  orchestrator — reads config once, routes by state
           └──────┬──────┘
                  ▼
  0.5  /qa-explore  (optional — live app discovery)
   │        │
   ▼        ▼
  1    /qa-plan       → TCs in qa/cases/**.yml + qa/test-plan.csv
   │
   ▼
  2    /qa-codegen    → Playwright / Maestro / XCUI specs in qa/tests/
   │
   ▼
  3    /qa-run        → execute + analyse + heal; reports in qa/reports/
   │
   ▼
  2.5  /qa-adversarial  (optional, post-run — edge-case battery against sandbox)
   │
   ▼
  4    /qa-testrail   (optional — push to TestRail)
        /qa-sync      (on each release — scan merged PRs, add new TCs)
        /qa-triage    (before QA cycle — score Jira tickets)
        /qa-ci        (one-time — write GitHub Actions workflows)
        /qa-bug       (failure → Jira/GitHub issue)
```

Each phase has an approval gate before the next runs. `[f] full run` from the menu chains Plan → Codegen → Run with one confirmation per step.

## Core Patterns

### Builder-Validator

Two-agent loop used in `/qa-plan` (and reused in `/qa-bug` confirm gate).

- **Builder** — planner agent writes all TC YAMLs from source docs.
- **Validator** — independent agent checks output against a strict schema/quality checklist. Returns `APPROVED` or `ISSUES: [...]`.
- Max 2 iterations. Third pass would mean the builder can't learn — surface issues to user instead.

Validator gets only the written files, never the builder's reasoning. This forces the builder to produce self-contained output and catches coverage / ID / schema drift.

### Information Barrier (`/qa-codegen`)

Prevents tests from mirroring their own expected results:

- **Agent A** receives TC YAMLs with `expected_result` **redacted**. Writes test code with `# ASSERT_HERE: {TC_ID}` markers where assertions belong.
- **Main context** builds `{ TC_ID → expected_result }` lookup map in memory from `qa/cases/**`. Map never touches disk.
- **Agent B** receives only the lookup map (no spec file paths, no access to `qa/cases/`). Replaces each `ASSERT_HERE` marker with a real assertion.

Consequence: Agent A can't copy the expected result into the test. Agent B can't see the test logic. Assertions stay independent of the code that produces the observed behavior.

### Immutability

Once a TC YAML is written, these fields are **immutable**:

- `id`, `title`, `steps`, `expected_result`, `preconditions`, `type`, `platform`, `priority`

Only these may be updated on existing TCs:

- `jira_key` (auto-link backfill)
- `automation_id` (codegen backfill)
- `automation_status` (`manual` → `automated` after codegen)
- `deprecated` (retire flow; never deletes)

Rationale: TC IDs are cited in bug reports, TestRail runs, Jira tickets, commit messages. Silent renumbering or rewording breaks cross-references across systems.

### Config Contract

`qa-config.yml` is read **once** by the `/qa` orchestrator. All resolved values are passed inline to sub-skills via `$VAR` names (see `skills/qa/SKILL.md`). Sub-skills never re-read the config file — this keeps main context flat and makes config changes predictable (next `/qa` run picks them up).

### Canonical TC Schema

`templates/tc.yml` is the single source of truth. All qa-* skills (qa-plan, qa-sync, qa-adversarial, qa-codegen, qa-testrail) read/write TCs conforming to this shape.

- `automation_status` defaults to `manual` on new TCs.
- `/qa-codegen` flips it to `automated` and backfills `automation_id`.
- Optional fields (`tags`, `owner`, `deprecated`, `obsoletes`) — absent is fine; when present, must match declared shape.

## Consumer Project Layout

In adopter projects, everything qa-related nests under `qa/`:

```
<project-root>/
├── .gitignore               # qa-init writes extensive ignore rules here
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

**Everything else local.** Reports, discovery artifacts, mapping state, source docs, framework outputs, build dirs.

## Non-obvious Invariants

- **Never** modify existing TC YAML fields except the allow-list above.
- **Never** delete TCs — use `deprecated: true`.
- **Never** push or auto-merge from a skill — PRs only (interactive or daily mode).
- **Never** block on Jira unavailability — auto-link is best-effort, always skippable.
- **Never** test adversarially against a dev server — `adversarial.base_url` must differ from `gen.playwright.base_url`.
- **Never** leak TC expected results into Agent A's codegen context.

## Adding a Framework

1. Add `gen.<name>:` block to `templates/qa-config.yml` with `enabled`, `root`, and framework-specific fields.
2. Add `## Framework: <Name>` section to `skills/qa-codegen/SKILL.md` — skip condition, file structure, element/locator rules, `ASSERT_HERE` marker syntax.
3. Add run command + heal block to `skills/qa-run/SKILL.md`.
4. The info barrier pattern, TC backfill, and immutability rules all apply unchanged.
