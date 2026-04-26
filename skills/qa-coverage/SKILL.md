# /qa-coverage — Coverage Report

Generates `qa/TEST-COVERAGE.md` — feature areas × TC counts × automation %, plus gap list (features in `$DOCS/` with no TCs). Feeds `qa-testrail adopt`.

Receives from orchestrator: `$CASES`, `$DOCS`, `$TESTS`, `$MODELS`, `$GEN`

## Step 0 — Scan

Main context builds feature → TC map by listing `$CASES/**/*.yml` via `find`. Never reads TC bodies.

Per-TC derivation via subagent (`$MODELS.default`):
- Feature group = top-level subfolder under `$CASES/` (kebab-case)
- Sub-feature = TC-ID middle segment (`X.Y.Z` → `X.Y`)
- Platform, type, priority, automation_status, deprecated — from YAML

Subagent returns structured tally. Never dumps raw TC bodies.

## Step 1 — Tally

```yaml
by_feature:
  <feature-group>:
    tc_count: N
    by_priority: { P1: n, P2: n, P3: n }
    by_type: { functional: n, regression: n, ... }
    by_platform: { web: n, mobile: n, backend: n, non_functional: n }
    automated: n                 # automation_status == automated
    manual: n
    deprecated: n                # excluded from totals below
    coverage_pct: float          # automated / (automated + manual)
totals:
  tc_count: N
  automated_pct: float
  by_priority: {...}
gaps:
  - doc: "qa/docs/billing.md"
    reason: "no TC referencing source_docs match"
```

## Step 2 — Gap Detection

Subagent compares `$DOCS/**/*.md|*.pdf|*.txt` filenames/paths against TC `source_docs` entries. Doc with zero TC references → gap.

False-positive guard: doc basename matched against feature-group folder names — ignore if fuzzy match > 0.8.

## Step 3 — Write `qa/TEST-COVERAGE.md`

Main context writes file from tally (no subagent — deterministic formatting).

```markdown
# Test Coverage

_Generated {YYYY-MM-DD} — do not edit by hand._

## Summary

| Metric | Value |
|--------|-------|
| Total TCs | N |
| Automated | n (X%) |
| Manual | n |
| Deprecated | n |

## By Feature

| Feature | TCs | P1 | P2 | P3 | Auto % |
|---------|-----|----|----|----|--------|
| billing | 12  | 4  | 6  | 2  | 75%    |
| ...

## By Platform

| Platform | TCs | Auto % |
|----------|-----|--------|
| web      | ... | ...    |

## Gaps

- `qa/docs/billing.md` — no TCs reference this doc
- ...
```

Deprecated TCs excluded from Auto %, included in raw counts with footnote.

## Step 4 — Return

Path + totals to orchestrator. No gate.

## Rules

- Never reads TC body text — only structural fields via subagent.
- Never writes to TC YAMLs.
- Overwrites previous `qa/TEST-COVERAGE.md` (idempotent regeneration).
- Gap list is advisory — not an error.
- Feeds `/qa-testrail adopt` which expects this file.
