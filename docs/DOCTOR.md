# Doctor Checks Reference

`/qa` runs these checks at startup before any pipeline work.

## Hard Fails (stop pipeline, exit non-zero)

All hard fails are collected and shown together before stopping.

| Check | How checked | Failure message |
|-------|-------------|----------------|
| RTK installed | `which rtk` | "rtk not found. Install: https://github.com/rtk-ai/rtk — required for token efficiency." |
| ANTHROPIC_API_KEY set | env var non-empty | "ANTHROPIC_API_KEY not set. Pipeline cannot spawn agents." |
| qa-config.yml exists + valid | parsed successfully | "qa/qa-config.yml missing or invalid. Run /qa-init." |
| Hooks installed | `.claude/hooks/pre_tool_use.py` exists | "qabot hooks not installed. Run /qa-init." |

If any hard fail fires: list all, stop. Do not run framework checks or show warnings.

## Warnings (show, ask to continue)

Warnings are shown as a list. User chooses `Continue? [y/n]`.

| Check | How checked | Warning message |
|-------|-------------|----------------|
| gh auth | `gh auth status 2>&1` exit 0 | "gh not authenticated. qa-sync and qa-ci will fail." |
| Jira MCP | Jira MCP tool available | "Jira MCP unavailable. Auto-linking and triage will be skipped." |
| TestRail creds | `.env` contains `TR_USER` (only if `testrail.enabled: true`) | "TestRail creds not found in .env. /qa-testrail will fail." |
| Obs server | `curl -s -m 2 http://localhost:4000/health` exit 0 | "Obs server not running. Start: bash obs/start-obs.sh" |

## Framework Checks (run after hard fails cleared, only for enabled frameworks)

| Framework | Check | Fatal |
|-----------|-------|-------|
| playwright | `npx --version` | Yes |
| playwright | `npx playwright --version` | Yes |
| playwright | `npm ls typescript @playwright/test @types/node` | Warn |
| playwright | `jq --version` | Warn |
| maestro | `maestro --version` | Yes |
| xcui | `xcodebuild -version` | Yes |
| api (supertest) | `node --version` | Yes |
| api (pytest) | `python3 --version` | Yes |
| api (rest-assured) | `mvn --version` | Yes |
| a11y | `npm ls @axe-core/playwright` | Warn |
| performance (lighthouse) | `lighthouse --version` | Yes |
| performance (k6) | `k6 version` | Yes |
| security (zap) | `zap.sh -version` | Yes |
| security (nuclei) | `nuclei -version` | Yes |
| espresso | `./gradlew --version` | Yes |
| espresso | `adb version` | Warn |

## RTK Integration Points

RTK wraps three operations in the pipeline:

```bash
# qa-plan: doc injection
rtk read {doc_file}

# qa-run: test execution
rtk test "npx playwright test {scope_flags}"
rtk test "maestro test {flow_path}"

# qa-sync: PR fetch
rtk gh pr list --state merged --base main --limit 50 --json number,title,body,files
```

RTK shows only failures + summary. Full output still saved to report files.

## Exit Codes

- Hard fail(s) present: exit non-zero (pipeline aborted)
- Warnings only, user continues: exit 0
- All clear: exit 0
