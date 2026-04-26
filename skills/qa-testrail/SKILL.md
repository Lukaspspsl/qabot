# /qa-testrail — TestRail Sync (Phase 4, optional)

Receives from orchestrator: `$CASES`, `$TC_FORMAT`, `$TC_DOMAINS`, `$TESTRAIL.url`, `$TESTRAIL.project_id`, `$TESTRAIL.suite_id`, `$SYNC_LOG`.

Push local TC YAMLs to TestRail. Diff + confirm + apply. Uses vendored `trsync/trsync.py`.

## Step 0 — Prerequisites

If `$TESTRAIL.url` empty or `$TESTRAIL.enabled` false:
```
Phase 4 requires testrail.enabled + testrail.url in qa-config.yml.
```
Stop.

**Env credentials** — probe `$CASES/.env` then project-root `.env` for `TR_USER`, `TR_API_KEY`, `TR_PASSWORD`:
```bash
ENV_FILE=""
for f in "$CASES/.env" "./.env"; do [ -f "$f" ] && ENV_FILE="$f" && break; done
```
If none found, or required keys missing:
```
Missing TestRail credentials. Copy skills/qa-testrail/trsync/.env.example to .env
and set TR_USER, TR_API_KEY, TR_PASSWORD.
```
Stop.

**Python deps** — `python3 -c "import typer, httpx, yaml, rich, dotenv, pydantic"`.
If fails:
```
Install deps: pip install -r skills/qa-testrail/trsync/requirements.txt
```
Stop.

## Step 1 — Validate (no network)

```bash
python3 skills/qa-testrail/trsync/trsync.py validate "$CASES"
```

Show pass/fail summary. On failure: print first errors, stop.

## Step 2 — Refresh mapping

```bash
mkdir -p .trsync
python3 skills/qa-testrail/trsync/trsync.py refresh-map
```
Writes `.trsync/mapping.json` (TC ID → TestRail case id).

## Step 3 — Diff

```bash
python3 skills/qa-testrail/trsync/trsync.py diff "$CASES" --out .trsync/diff.txt
```

Parse tail of output for counts. Show:
```
TestRail diff: NEW={N}  CHANGED={M}  UP_TO_DATE={K}
Detail: .trsync/diff.txt
```

If `NEW + CHANGED == 0`: print `Nothing to push.` — stop.

## Step 4 — Gate

```
Push N new / M changed to TestRail ({$TESTRAIL.url})?
[y] yes  [r] review diff  [n] cancel
```

`r` → open `.trsync/diff.txt` in pager, return to gate.

## Step 5 — Dry-run push

```bash
python3 skills/qa-testrail/trsync/trsync.py push "$CASES"
```
(no `--apply` → dry-run). Surface orphan / missing-section warnings verbatim.

Gate again:
```
Dry-run OK. Apply to TestRail? [y/n]
```

## Step 6 — Apply

```bash
python3 skills/qa-testrail/trsync/trsync.py push "$CASES" --apply
```

Capture `created=X updated=Y` from output.

## Step 7 — Post-push

```bash
python3 skills/qa-testrail/trsync/trsync.py refresh-map
```

Append to `$SYNC_LOG`:
```
YYYY-MM-DD: testrail push — X created, Y updated
```

Return summary to orchestrator: `created=X updated=Y`.

## Advanced sub-commands

Behind a `[tr] > advanced` prompt — each runs dry-run, shows diff, confirms before `--apply`.

| Cmd | Effect |
|-----|--------|
| `normalize` | Canonicalize TestRail titles (`TC-XXX-N.N.N Title`) |
| `adopt` | Fuzzy-match orphan TestRail cases vs local TCs / TEST-COVERAGE.md |
| `renumber OLD NEW` | Rewrite TC ID prefix (e.g. legacy `TC-001` → `$TC_FORMAT`) |

Invocation:
```bash
python3 skills/qa-testrail/trsync/trsync.py <cmd> "$CASES"           # dry-run
python3 skills/qa-testrail/trsync/trsync.py <cmd> "$CASES" --apply   # commit
```

## Rules

- Never commit `.env` or `.trsync/mapping.json` (project `.gitignore` responsibility).
- Always dry-run before apply. No silent writes to TestRail.
- On auth failure (`401` / `login failed`): stop, print exact error, do not retry.
- Mapping cache lives at `.trsync/mapping.json` under the consumer project root.
- Skill never mutates local YAMLs — TestRail sync is one-way (local → TestRail).
