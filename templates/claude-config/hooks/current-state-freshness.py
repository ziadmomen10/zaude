#!/usr/bin/env python3
"""Zaude — SessionEnd status-freshness logger.

Reports whether current-state.md contains a fresh <!-- status-freshness -->
block. The report goes to stderr (shown to user by Claude Code's harness).

IMPORTANT — architectural honesty: Claude Code's SessionEnd hooks CANNOT
block anything. Per the official docs, exit codes 1/2 at SessionEnd print
stderr but do not prevent the session from ending and do not gate other
hooks. This script's role is observability only.

The REAL freshness gate lives in two places:

  1. The `/wrap` skill runs `current-state-freshness.py --check` AFTER
     regen and HALTS if the check reports violations. This is where Claude
     is still engaged and can respond to the error.

  2. `session-end-vault-sync.sh` calls this script and refuses to sync
     current-state.md if a violation is reported (everything else still
     syncs). This means a stale block never reaches GitHub.

  3. SessionStart (`session-start-vault.py`) injects a loud warning at the
     top of Claude's context if the block is missing/stale. This catches
     any session that bypassed the above.

This script's exit code is always 0 in hook mode (no ability to gate).
When invoked with --check (from /wrap or the sync script), exit 1 signals
"stale or missing block" to the caller, which MAY act on it.

Env vars:
  FRESHNESS_ENFORCE=1   — in --check mode, surface all issues as exit 1.
                          Unset/0 is log-only even in --check mode.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import sys

# Put lib/ on sys.path so we can import the shared parser.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from freshness_parse import (  # type: ignore  # noqa: E402
    BLOCK_RE,
    ISO_DATE_RE,
    MAX_LOG_BYTES,
    RATIO_RE,
    REQUIRED_SCENARIO_FIELDS,
    REQUIRED_TOP_FIELDS,
    parse_block_yaml,
    read_capped,
)


def enforce_mode() -> bool:
    return os.environ.get("FRESHNESS_ENFORCE", "0").strip().lower() in {"1", "true", "yes"}


def report(msg: str) -> None:
    sys.stderr.write(msg if msg.endswith("\n") else msg + "\n")


def violation(summary: str, expected: str, found: str, fix: str) -> str:
    return (
        f"[FRESHNESS] {summary}\n"
        f"  Expected: {expected}\n"
        f"  Found:    {found}\n"
        f"  Fix:      {fix}"
    )


def load_config() -> dict:
    path = os.path.expanduser("~/.zaude/config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def detect_project(cwd: str, vault_root: str, cwd_map: dict) -> str | None:
    probe = cwd
    for _ in range(5):
        base = os.path.basename(probe.rstrip("/\\"))
        if not base:
            break
        mapped = cwd_map.get(base)
        if mapped and os.path.isdir(os.path.join(vault_root, mapped)):
            return mapped
        if os.path.isdir(os.path.join(vault_root, base)):
            return base
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return None


def validate_path_contained(child: str, parent: str) -> bool:
    """Return True iff child resolves inside parent. Guards against path
    traversal via config-derived values (vault_path, cwd_to_project)."""
    try:
        child_abs = os.path.realpath(child)
        parent_abs = os.path.realpath(parent)
    except OSError:
        return False
    try:
        common = os.path.commonpath([child_abs, parent_abs])
    except ValueError:
        return False
    return common == parent_abs


def latest_session_log(sessions_dir: str) -> str | None:
    if not os.path.isdir(sessions_dir):
        return None
    files = sorted(glob.glob(os.path.join(sessions_dir, "*.md")))
    return os.path.basename(files[-1]) if files else None


def body_without_block(text: str) -> str:
    return BLOCK_RE.sub("", text)


def contradiction_warnings(body: str, scenarios: list) -> list[str]:
    out: list[str] = []
    for m in RATIO_RE.finditer(body):
        ratio, noun = m.group(1), m.group(2)
        if len(noun) < 4:
            continue  # skip short nouns like "vs", "to" — too noisy
        matched = False
        for s in scenarios:
            if not isinstance(s, dict):
                continue
            claim = str(s.get("claim", "")).lower()
            if ratio in claim and noun.lower() in claim:
                matched = True
                break
        if not matched:
            out.append(
                f'Body text says "{ratio} {noun}" but no matching verified '
                f"scenario found in the block. The block may be stale."
            )
    return out


def validate_current_state(cwd: str) -> list[str]:
    """Return a list of violation strings (empty = all good)."""
    violations: list[str] = []
    warnings: list[str] = []

    config = load_config()
    if not config:
        return violations  # no config = guard disabled (matches frozen-guard posture)

    vault_path = os.path.expanduser(config.get("vault_path") or "")
    if not vault_path or not os.path.isdir(vault_path):
        return violations

    projects_subdir = config.get("projects_subdir") or "01-projects"
    cwd_map = config.get("cwd_to_project") or {}
    vault_root = os.path.join(vault_path, projects_subdir)

    # Path containment guard — prevents config-driven traversal.
    if not validate_path_contained(vault_root, vault_path):
        violations.append(
            violation(
                "projects_subdir escapes vault_path",
                "projects_subdir stays under vault_path",
                f"vault_root={vault_root} is not inside vault_path={vault_path}",
                "Fix projects_subdir in ~/.zaude/config.json",
            )
        )
        return violations

    project = detect_project(cwd, vault_root, cwd_map)
    if not project:
        return violations  # cwd not in a vault project — skip silently

    vault_dir = os.path.join(vault_root, project)
    if not validate_path_contained(vault_dir, vault_path):
        violations.append(
            violation(
                f"project path '{project}' escapes vault_path",
                "cwd_to_project entries stay under vault_path",
                f"vault_dir={vault_dir} is not inside vault_path={vault_path}",
                "Fix cwd_to_project in ~/.zaude/config.json",
            )
        )
        return violations

    state_path = os.path.join(vault_dir, "current-state.md")
    sessions_dir = os.path.join(vault_dir, "sessions")

    if not os.path.isfile(state_path):
        violations.append(
            violation(
                f"current-state.md not found for project '{project}'",
                f"File at {state_path}",
                "File missing",
                "Create current-state.md or verify the vault path is correct",
            )
        )
        return violations

    text = read_capped(state_path, MAX_LOG_BYTES)
    if not text:
        violations.append(
            violation(
                "current-state.md is empty or unreadable",
                "Non-empty readable file",
                "Empty",
                "Check filesystem permissions",
            )
        )
        return violations

    match = BLOCK_RE.search(text)
    if not match:
        violations.append(
            violation(
                "current-state.md has no status-freshness block",
                "<!-- status-freshness ... --> block present in the file",
                "No such block",
                "Run /wrap to regenerate the block via regen-freshness.py",
            )
        )
        return violations

    parsed, parse_err = parse_block_yaml(match.group(1))
    if parsed is None:
        violations.append(
            violation(
                "status-freshness block is unparseable",
                "Valid YAML inside <!-- status-freshness ... -->",
                parse_err or "parse error",
                "Run /wrap to regenerate the block; do not hand-edit YAML inside the comment",
            )
        )
        return violations

    for field in REQUIRED_TOP_FIELDS:
        if field not in parsed or parsed.get(field) in (None, ""):
            violations.append(
                violation(
                    f"status-freshness block is missing required field: {field}",
                    f"Field '{field}' present and non-empty",
                    "Field absent or null",
                    "Run /wrap to regenerate the block",
                )
            )
            return violations

    last_updated = str(parsed.get("last_updated") or "").strip()
    if not ISO_DATE_RE.match(last_updated):
        violations.append(
            violation(
                "last_updated is not an ISO date",
                "YYYY-MM-DD format",
                f"'{last_updated}'",
                "Run /wrap to regenerate the block",
            )
        )
        return violations

    today = datetime.date.today()
    try:
        block_date = datetime.date.fromisoformat(last_updated)
    except ValueError:
        violations.append(
            violation(
                "last_updated is not a valid calendar date",
                "YYYY-MM-DD (valid ISO date)",
                f"'{last_updated}'",
                "Run /wrap to regenerate the block",
            )
        )
        return violations

    delta = (today - block_date).days
    if delta < 0:
        warnings.append(
            f"last_updated ({last_updated}) is in the future relative to today ({today})"
        )
    elif delta > 1:
        violations.append(
            violation(
                "status-freshness block last_updated is stale",
                f"last_updated == {today.isoformat()} (or {today.isoformat()} - 1 day UTC tolerance)",
                f"last_updated == {last_updated}",
                f"Run /wrap at the end of this session to refresh the block. "
                f"Tolerance: today or yesterday — older requires a new wrap.",
            )
        )
        return violations
    elif delta == 1:
        warnings.append(
            f"last_updated ({last_updated}) is one day behind today ({today}); UTC boundary tolerance applied"
        )

    last_log = str(parsed.get("last_session_log") or "").strip()
    latest = latest_session_log(sessions_dir)
    if latest is not None:
        expected = f"sessions/{latest}"
        if last_log != expected:
            violations.append(
                violation(
                    "status-freshness block last_session_log does not point to the latest log",
                    expected,
                    last_log or "<empty>",
                    "Run /wrap; if the session log for today does not exist yet, create it first",
                )
            )
            return violations

    scenarios = parsed.get("verified_scenarios") or []
    if not isinstance(scenarios, list):
        violations.append(
            violation(
                "verified_scenarios is not a list",
                "YAML list of scenario objects",
                f"type '{type(scenarios).__name__}'",
                "Run /wrap to regenerate the block",
            )
        )
        return violations

    if len(scenarios) == 0:
        warnings.append("verified_scenarios list is empty — no claims recorded this session")
    else:
        seen_names: set[str] = set()
        for i, s in enumerate(scenarios):
            if not isinstance(s, dict):
                violations.append(
                    violation(
                        f"verified_scenarios[{i}] is not an object",
                        "YAML mapping with name, claim, source, date",
                        f"type '{type(s).__name__}'",
                        "Run /wrap to regenerate the block",
                    )
                )
                return violations
            for field in REQUIRED_SCENARIO_FIELDS:
                if field not in s or s.get(field) in (None, ""):
                    violations.append(
                        violation(
                            f"verified_scenarios[{i}] missing required field: {field}",
                            f"Field '{field}' present and non-empty",
                            "Field absent or null",
                            "Run /wrap to regenerate the block",
                        )
                    )
                    return violations
            name = str(s["name"])
            if name in seen_names:
                warnings.append(f"duplicate scenario name: '{name}'")
            seen_names.add(name)

    # Warn-only: body-text contradictions
    body_text = body_without_block(text)
    for w in contradiction_warnings(body_text, scenarios):
        warnings.append(w)

    if match.start() > 500:
        warnings.append("status-freshness block is not near the top of current-state.md")

    for w in warnings:
        report(f"[FRESHNESS WARN] {w}")

    return violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check",
        action="store_true",
        help="Check mode: invoked by /wrap or sync script. Exit 1 on violations "
        "when FRESHNESS_ENFORCE=1. Hook mode (default) always exits 0.",
    )
    ap.add_argument(
        "--cwd",
        default=None,
        help="Override cwd (for --check mode from /wrap). Defaults to stdin cwd in hook mode, getcwd() otherwise.",
    )
    args = ap.parse_args()

    if args.check:
        cwd = args.cwd or os.getcwd()
    else:
        # Hook mode — read stdin JSON
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0
        cwd = (data.get("cwd") or "").strip()
        if not cwd:
            return 0

    violations = validate_current_state(cwd)

    for v in violations:
        report(v)

    if violations:
        if args.check and enforce_mode():
            return 1
        if not args.check:
            # Hook mode: SessionEnd cannot block. Log and exit 0.
            report(
                "[FRESHNESS] NOTE: SessionEnd cannot block. The real gate runs "
                "in /wrap (step 8b) and session-end-vault-sync.sh."
            )
            return 0
        # --check without enforce: warn-only
        return 0

    if args.check:
        report("[FRESHNESS] OK — status-freshness block is present and fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
