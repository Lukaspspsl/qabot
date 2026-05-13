# TC Schema Reference (v1)

All test case YAML files produced by qabot skills must conform to this schema.

## Fields

| Field | Type | Mutability | Required | Description |
|-------|------|-----------|----------|-------------|
| `schema_version` | integer | immutable | yes | Always `1` for v1 schema |
| `id` | string | immutable | yes | `TC-{DOM}-{X}.{Y}.{Z}` — domain from `tc_id.domains` |
| `title` | string | immutable | yes | Concise, action-oriented description |
| `priority` | enum | immutable | yes | `critical` \| `high` \| `medium` \| `low` |
| `platform` | enum | immutable | yes | `web` \| `mobile` \| `ios` \| `backend` \| `non_functional` |
| `type` | enum | immutable | yes | `functional` \| `integration` \| `e2e` \| `regression` \| `performance` \| `security` \| `a11y` |
| `preconditions` | list[string] | immutable | yes | Conditions that must be true before test runs |
| `steps` | string \| list | immutable | yes | Depends on `tc_format` (see below) |
| `expected_result` | string | immutable | yes | Observable outcome (see format below) |
| `automation_status` | enum | **mutable** | yes | `manual` \| `automated` \| `skipped` |
| `automation_id` | map | **mutable** | yes | YAML map keyed by framework name (empty map OK) |
| `jira_key` | string | **mutable** | yes | Jira issue key(s), space-separated. Empty string OK |
| `source_docs` | list[string] | immutable | yes | Doc filenames used during planning |
| `deprecated` | boolean | **mutable** | yes | `true` = excluded from runs; never deleted |
| `tags` | list[string] | optional | no | Slice keys e.g. `["smoke", "regression-q2"]` |
| `owner` | string | optional | no | Individual or team responsible |
| `obsoletes` | list[string] | optional | no | TC IDs this case supersedes |

### Immutable fields

Locked after first write: `schema_version`, `id`, `title`, `priority`, `platform`, `type`, `preconditions`, `steps`, `expected_result`, `source_docs`.

The `pre_tool_use.py` hook enforces this when `QABOT_TC_IMMUTABLE=1` is set.

### Mutable fields

May be updated post-creation: `automation_status`, `automation_id`, `jira_key`, `deprecated`.

---

## TC ID Format

`TC-{DOM}-{X}.{Y}.{Z}`

- `{DOM}` — domain abbreviation from `tc_id.domains` in `qa-config.yml`
- `{X}` — feature group number
- `{Y}` — sub-feature number
- `{Z}` — case number within sub-feature

Default domain map:

| Platform field | Domain key | Default abbreviation |
|----------------|------------|---------------------|
| `web` | `web` | `WEB` |
| `mobile` | `mobile` | `MOB` |
| `backend` | `backend` | `BE` |
| `non_functional` | `non_functional` | `NF` |
| `ios` | `ios` | `IOS` (if added) |

IDs are **immutable and append-only** — never renumber, never change after first write.

---

## TC Verbosity Formats

Controlled by `tc_format` in `qa-config.yml`. Default: `B`.

### Format A — Title + Result Only

Steps omitted. TC described entirely by title + expected result.

```yaml
schema_version: 1
id: TC-WEB-1.1.1
title: "User logs in with valid credentials"
priority: high
platform: web
type: functional
preconditions:
  - "User account exists with valid credentials"
steps: ""
expected_result: "User is redirected to dashboard and session cookie is set"
automation_status: manual
automation_id: {}
jira_key: ""
source_docs: ["auth-spec.md"]
deprecated: false
```

### Format B — Single Step Block (Default)

Steps written as a single prose block. Expected result is the outcome of the whole test.

```yaml
schema_version: 1
id: TC-WEB-1.1.1
title: "User logs in with valid credentials"
priority: high
platform: web
type: functional
preconditions:
  - "User account exists with valid credentials"
steps: "Navigate to /login. Enter valid email and password. Click 'Sign In'."
expected_result: "User is redirected to dashboard and session cookie is set"
automation_status: manual
automation_id: {}
jira_key: ""
source_docs: ["auth-spec.md"]
deprecated: false
```

### Format C — Verbose Per-Step

Steps is a list, each entry has `step` and `expected`. Top-level `expected_result` = overall outcome.

```yaml
schema_version: 1
id: TC-WEB-1.1.1
title: "User logs in with valid credentials"
priority: high
platform: web
type: functional
preconditions:
  - "User account exists with valid credentials"
steps:
  - step: "Navigate to /login"
    expected: "Login form displayed with email and password fields"
  - step: "Enter valid email and password"
    expected: "Fields populated correctly, no validation error"
  - step: "Click 'Sign In'"
    expected: "Loading indicator shown, then redirect to /dashboard"
expected_result: "User is authenticated, redirected to dashboard, session cookie is set"
automation_status: manual
automation_id: {}
jira_key: ""
source_docs: ["auth-spec.md"]
deprecated: false
```

---

## automation_id Format

YAML map keyed by framework config key (never aliases like `web` or `mobile`):

```yaml
automation_id:
  playwright: qa/tests/web/specs/auth/tc-web-1-1-1.spec.ts
  maestro: qa/tests/mobile/flows/tc-mob-1-1-1.yaml
  xcui: qa/tests/ios/Tests/AuthTests/tc-ios-1-1-1.swift
```

Multi-framework: add keys without overwriting existing ones.

Empty map (unautomated):

```yaml
automation_id: {}
```

---

## Migration Guide: Old Format → v1

Run `qabot update` (or `/qa-init` update flow) to migrate existing TCs.

### Changes applied automatically

1. **Add `schema_version: 1`** — inserted as first field.

2. **Convert string `automation_id` to YAML map** — heuristic: if value contains `playwright` or `spec.ts`, key as `playwright`. If contains `maestro` or `.yaml`, key as `maestro`. Otherwise key as `playwright` (safest default).

   Before:
   ```yaml
   automation_id: "tests/web/specs/auth/tc-web-1-1-1.spec.ts"
   ```
   After:
   ```yaml
   automation_id:
     playwright: tests/web/specs/auth/tc-web-1-1-1.spec.ts
   ```

3. **Convert comma-separated `automation_id` string to map** — split on `,`, parse `framework:path` pairs.

   Before:
   ```yaml
   automation_id: "playwright:tests/web/specs/auth/tc-web-1-1-1.spec.ts,maestro:tests/mobile/flows/tc-mob-1-1-1.yaml"
   ```
   After:
   ```yaml
   automation_id:
     playwright: tests/web/specs/auth/tc-web-1-1-1.spec.ts
     maestro: tests/mobile/flows/tc-mob-1-1-1.yaml
   ```

### Changes requiring user input

4. **Add domain to domain-free ID** — old format `TC-1.1.1` has no domain prefix. User prompted:
   ```
   TC-1.1.1 has no domain. Assign [WEB/MOB/BE/NF]: _
   ```
   Renamed to `TC-WEB-1.1.1` (both `id` field and filename).

### After migration

- `test-plan.csv` regenerated from migrated TCs.
- All migrated files shown as diff preview before applying.
