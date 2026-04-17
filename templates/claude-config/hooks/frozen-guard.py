#!/usr/bin/env python3
"""Zaude — PreToolUse frozen-zone guard.

Blocks any Edit/Write whose file_path contains any substring listed in
~/.zaude/config.json `frozen_zones`. Frozen zones are directories or
project names you never want Claude to modify without explicit plain-language
override (e.g. production repos, legacy code you've agreed is read-only).

Emits a PreToolUse deny decision on hit; exits 0 with no output to allow.
If the config is missing or invalid, the guard is effectively disabled
(allow-all) — never blocks the tool call via error.
"""
import json
import os
import sys


def load_frozen_zones() -> list[str]:
    path = os.path.expanduser("~/.zaude/config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    zones = config.get("frozen_zones") or []
    if not isinstance(zones, list):
        return []
    return [str(z) for z in zones if z]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    zones = load_frozen_zones()
    if not zones:
        return 0  # guard disabled

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        return 0

    hit = next((z for z in zones if z in file_path), None)
    if not hit:
        return 0

    reason = (
        f"BLOCKED: {file_path} is inside the frozen zone '{hit}'. "
        "This path is read-only by Zaude configuration (~/.zaude/config.json). "
        "If you genuinely intend to modify this file, tell Claude in plain "
        "language to override the frozen guard and retry, or remove the zone "
        "from ~/.zaude/config.json."
    )

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
