#!/usr/bin/env python3
"""
pre_tool_use.py — QA safety gate + information barrier enforcement.
Blocks dangerous operations and enforces Agent A/B separation.
"""

import json
import os
import re
import sys

def _split_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [p.strip() for p in raw.split(",") if p.strip()]


DEFAULT_BLOCKED_BASH_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
    r">\s*/etc/",
]

BLOCKED_URL_PATTERNS = _split_env("QABOT_BLOCKED_URLS")
BLOCKED_BASH_PATTERNS = _split_env("QABOT_BLOCKED_BASH") or DEFAULT_BLOCKED_BASH_PATTERNS

WORKSPACE_ROOT = os.environ.get("QABOT_WORKSPACE", "")
AGENT_ROLE = os.environ.get("QABOT_AGENT_ROLE", "")


def read_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def block(reason: str):
    os.environ["QABOT_EVENT_STATUS"] = "BLOCKED"
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def warn(reason: str):
    """Emit WARN — does not block, creates audit trail."""
    os.environ["QABOT_EVENT_STATUS"] = "WARN"
    print(json.dumps({"decision": "warn", "reason": reason}), file=sys.stderr)


def allow():
    sys.exit(0)


def check_bash(tool_input: dict):
    command = tool_input.get("command", "")
    for pattern in BLOCKED_BASH_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            block(f"Blocked dangerous bash command matching: {pattern!r}")
    if WORKSPACE_ROOT and WORKSPACE_ROOT not in command:
        if re.search(r"\bwrite\b|\btee\b|>\s*\S", command, re.IGNORECASE):
            os.environ["QABOT_EVENT_STATUS"] = "WARN"


def check_web_fetch(tool_input: dict):
    url = tool_input.get("url", "")
    for pattern in BLOCKED_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            block(f"Blocked request to production URL: {url!r}")


def check_write(tool_input: dict):
    file_path = tool_input.get("file_path", "")
    if WORKSPACE_ROOT and not file_path.startswith(WORKSPACE_ROOT):
        os.environ["QABOT_EVENT_STATUS"] = "WARN"


def extract_file_path(tool_name: str, tool_input: dict) -> str:
    """Extract the file path being accessed from tool input."""
    if tool_name == "Read":
        return tool_input.get("file_path", "")
    if tool_name == "Grep":
        return tool_input.get("path", "")
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        for pattern in [r"\bcat\s+(\S+)", r"\bhead\s+.*?(\S+)$", r"\btail\s+.*?(\S+)$"]:
            m = re.search(pattern, cmd)
            if m:
                return m.group(1)
    return ""


def check_information_barrier(tool_name: str, tool_input: dict):
    """Enforce Agent A/B information barrier during codegen phase."""
    if not AGENT_ROLE:
        return

    file_path = extract_file_path(tool_name, tool_input)
    if not file_path:
        return

    if AGENT_ROLE == "B":
        blocked_patterns = ["/qa/cases/", "/qa/docs/", "QA_CONTEXT.md"]
        for pat in blocked_patterns:
            if pat in file_path:
                block(f"Agent B barrier: blocked read of {file_path} (matches {pat})")

    elif AGENT_ROLE == "A":
        if "/qa/cases/" in file_path:
            warn(f"Agent A reading case file: {file_path}")


def main():
    payload = read_stdin()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    check_information_barrier(tool_name, tool_input)

    if tool_name == "Bash":
        check_bash(tool_input)
    elif tool_name in ("WebFetch", "mcp__fetch"):
        check_web_fetch(tool_input)
    elif tool_name == "Write":
        check_write(tool_input)

    allow()


if __name__ == "__main__":
    main()
