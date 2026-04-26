#!/usr/bin/env python3
"""
send_event.py — Universal event sender for qabot obs.
Called by Claude Code hooks after every tool use.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

SERVER_URL = os.environ.get("OBS_SERVER_URL", "http://localhost:4000")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--source-app", default="qabot")
    p.add_argument("--event-type", required=True)
    return p.parse_args()


def read_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def extract_detail(tool_name: str, tool_input: dict) -> str:
    """Extract a human-readable detail string from tool input."""
    if not tool_input:
        return ""

    if tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path", "")
        if path:
            # Show last 2-3 path segments for readability
            parts = path.rstrip("/").split("/")
            short = "/".join(parts[-3:]) if len(parts) > 3 else path
            if tool_name == "Edit":
                return short
            return short

    if tool_name == "Glob":
        return tool_input.get("pattern", "")

    if tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        if path:
            parts = path.rstrip("/").split("/")
            short = "/".join(parts[-2:]) if len(parts) > 2 else path
            return f"{pattern}  in {short}" if pattern else short
        return pattern

    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Show first 80 chars of command
        return cmd[:80] + ("..." if len(cmd) > 80 else "")

    if tool_name == "Agent":
        return tool_input.get("description", "")[:60]

    if tool_name in ("WebFetch", "mcp__fetch"):
        return tool_input.get("url", "")[:80]

    if tool_name == "Skill":
        return tool_input.get("skill", "")

    return ""


def extract_qa_fields(payload: dict) -> dict:
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    return {
        "tool_name": tool_name,
        "tool_use_id": payload.get("tool_use_id", ""),
        "test_name": os.environ.get("QABOT_TEST_NAME", ""),
        "test_step": os.environ.get("QABOT_TEST_STEP", ""),
        "status": os.environ.get("QABOT_EVENT_STATUS", "INFO"),
        "detail": extract_detail(tool_name, tool_input if isinstance(tool_input, dict) else {}),
    }


def build_event(args, payload: dict) -> dict:
    return {
        "source_app": args.source_app,
        "session_id": payload.get("session_id", "unknown"),
        "hook_event_type": args.event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        **extract_qa_fields(payload),
    }


def send(event: dict) -> bool:
    try:
        data = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            f"{SERVER_URL}/events",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    args = parse_args()
    payload = read_stdin()
    event = build_event(args, payload)
    send(event)
    sys.exit(0)


if __name__ == "__main__":
    main()
