#!/usr/bin/env python3
"""
post_tool_use.py — QA assertion parser.
Detects PASS/FAIL from tool output and writes status to temp file.
"""

import json
import re
import sys

PASS_PATTERNS = [
    r"\bPASSED\b", r"\b✓\b", r"\ball tests passed\b",
    r"\d+ passed", r"\bTests:.*\d+ passed", r"✔", r"\bok\b",
    r"Status:\s*200", r'"status":\s*"pass"',
]

FAIL_PATTERNS = [
    r"\bFAILED\b", r"\bFAIL\b", r"\b✗\b", r"✘",
    r"\bAssertionError\b", r"\bTraceback\b", r"\bError:\b",
    r"\d+ failed", r"\bTests:.*\d+ failed",
    r"Status:\s*[45]\d\d", r'"status":\s*"fail"',
]


def read_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def detect_status(output: str) -> str:
    for pattern in FAIL_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            return "FAIL"
    for pattern in PASS_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            return "PASS"
    return "INFO"


def main():
    payload = read_stdin()
    tool_output = payload.get("tool_response", "") or ""
    if isinstance(tool_output, dict):
        tool_output = json.dumps(tool_output)
    elif isinstance(tool_output, list):
        tool_output = " ".join(str(x) for x in tool_output)

    status = detect_status(str(tool_output))
    with open("/tmp/qabot_last_status", "w") as f:
        f.write(status)
    sys.exit(0)


if __name__ == "__main__":
    main()
