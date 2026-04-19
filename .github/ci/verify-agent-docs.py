#!/usr/bin/env python3
"""
verify-agent-docs.py — CI check for v0.5 VoltAgent specialist documentation parity.

Verifies that every expected v0.5 agent name appears at least once in each of the
authoritative documentation files. This catches drift where a new agent is added
to the dispatch matrix but not the docs, or vice versa.

Python stdlib only (Zaude hard rule: no pip dependencies in hooks or CI scripts).

Exit 0 = all agents mentioned in all required files.
Exit 1 = any agent missing from any required file.

Canonical agent list is hard-coded below. When Zaude adds or removes a v0.5
specialist, update EXPECTED_V05_AGENTS here in the same PR as the doc changes.
"""

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


# Canonical v0.5 VoltAgent specialist roster.
# Keep sorted; update when Zaude adds or removes a specialist.
EXPECTED_V05_AGENTS = [
    "accessibility-tester",
    "debugger",
    "docker-expert",
    "documentation-engineer",
    "mcp-developer",
    "postgres-pro",
    "prompt-engineer",
    "python-pro",
    "react-specialist",
    "refactoring-specialist",
    "sql-pro",
]


# Files where every expected agent must be mentioned at least once.
# (These are the authoritative surfaces for agent dispatch and install.)
REQUIRED_MENTIONS = [
    "templates/vault/03-patterns/agent-usage.md",
    "docs/08-agents.md",
    "CHANGELOG.md",
]


def main() -> int:
    errors = []

    for relpath in REQUIRED_MENTIONS:
        path = REPO / relpath
        if not path.is_file():
            errors.append(f"Required file missing: {relpath}")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"Cannot read {relpath}: {e}")
            continue

        for agent in EXPECTED_V05_AGENTS:
            if agent not in content:
                errors.append(f"{relpath}: no mention of '{agent}'")

    if errors:
        print("FAIL: v0.5 agent documentation parity", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    n_agents = len(EXPECTED_V05_AGENTS)
    n_files = len(REQUIRED_MENTIONS)
    print(f"OK: all {n_agents} v0.5 agents mentioned in each of {n_files} required files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
