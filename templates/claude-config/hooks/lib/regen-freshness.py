#!/usr/bin/env python3
"""Zaude — /wrap helper: regenerate the status-freshness block in current-state.md.

Mechanically parses today's session log for verified claims, then writes a
well-formed <!-- status-freshness --> block at the top of current-state.md
(under the H1, before the first ---). If a block already exists anywhere
in the file, it's replaced in-place via regex swap — the rest of the file
is untouched byte-for-byte.

Called from /wrap BEFORE the commit step so the SessionEnd freshness
validator never blocks a legitimate wrap.

Usage:
  python ~/.claude/hooks/lib/regen-freshness.py [--project SLUG] [--log YYYY-MM-DD]

Both flags are optional. If --project is omitted, the tool infers it from
cwd via ~/.zaude/config.json (same rules as session-start-vault.py). If
--log is omitted, it uses today's session log filename.

Exit codes:
  0 = block written or updated (even if empty scenarios)
  1 = fatal (cannot find vault, project, or state file)
  2 = today's session log does not exist; caller should create it first
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import sys
import tempfile

# lib/ is our own directory — import siblings directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freshness_parse import (  # type: ignore  # noqa: E402
    BLOCK_RE_SPLICE,
    ISO_DATE_RE,
    MAX_LOG_BYTES,
    read_capped,
)

H1_RE = re.compile(r"^#\s+.+$", re.MULTILINE)

RATIO_PATTERN = re.compile(r"(\d+/\d+)\s+(\w{4,})\b(.{0,60})", re.UNICODE)
CHECKED_PATTERN = re.compile(
    r"^\s*-\s+\[x\]\s+verified[:\s]+(.{3,160})",
    re.MULTILINE | re.IGNORECASE,
)
VERIFIED_PATTERN = re.compile(
    r"verified[:\s]+(.{8,120})",
    re.IGNORECASE,
)
CONFIDENCE_PATTERN = re.compile(
    r"\b(shipped|end-to-end|green)\b([^\n]{10,120})",
    re.IGNORECASE,
)

# Stopwords disqualify a ratio's trailing noun as a claim (e.g., "15/15 vs 12").
RATIO_STOPWORDS = {
    "vs", "not", "and", "the", "out", "was", "are", "has", "had", "but",
    "for", "with", "from", "over", "into", "this", "that", "than", "just",
    "when", "then", "only", "even", "also",
}

# Cap total scenarios to avoid flooding the block with low-signal claims.
MAX_SCENARIOS = 5


def err(msg: str) -> None:
    sys.stderr.write(f"[regen-freshness] {msg}\n")


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


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9\s\-]", "", text.lower())
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:max_len] if s else "unnamed"


def truncate(text: str, max_len: int = 160) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    # Strip orphan trailing punctuation that often leaks from parenthetical phrases.
    t = re.sub(r"[\s\)\]\,\.\;\:—\-]+$", "", t)
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def extract_scenarios(log_text: str, log_basename: str, log_date: str) -> list[dict]:
    """Four pattern classes, priority order. Dedupe by name (first wins)."""
    scenarios: list[dict] = []
    names: set[str] = set()
    source = f"sessions/{log_basename}"

    ratios_seen: set[str] = set()
    consumed: list[tuple[int, int]] = []  # (start, end) char ranges already claimed

    def overlaps_consumed(start: int, end: int) -> bool:
        for cs, ce in consumed:
            if not (end <= cs or start >= ce):
                return True
        return False

    def add(name: str, claim: str, span: tuple[int, int] | None = None) -> bool:
        if not name or not claim or len(scenarios) >= MAX_SCENARIOS:
            return False
        name = slugify(name)
        if name in names:
            return False
        names.add(name)
        scenarios.append({
            "name": name,
            "claim": truncate(claim),
            "source": source,
            "date": log_date,
        })
        if span is not None:
            consumed.append(span)
        return True

    # 1. Checked list items — highest signal.
    for m in CHECKED_PATTERN.finditer(log_text):
        claim = m.group(1).strip()
        name_words = claim.split()[:3]
        add(" ".join(name_words), claim, (m.start(), m.end()))
        if len(scenarios) >= MAX_SCENARIOS:
            return scenarios

    # 2. Ratio phrases — dedupe by ratio, drop stopwords, require noun >= 4 chars.
    for m in RATIO_PATTERN.finditer(log_text):
        if len(scenarios) >= MAX_SCENARIOS:
            return scenarios
        if overlaps_consumed(m.start(), m.end()):
            continue
        ratio = m.group(1)
        if ratio in ratios_seen:
            continue
        noun = m.group(2).strip().lower()
        if noun in RATIO_STOPWORDS:
            continue
        ratios_seen.add(ratio)
        tail = m.group(3).strip(" :-,.")
        claim = f"{ratio} {noun}"
        if tail:
            claim = f"{claim} {tail}"
        add(f"{noun}-{ratio.replace('/', '-')}", claim, (m.start(), m.end()))

    # 3. Verified markers — explicit "verified: ..." phrasing.
    for m in VERIFIED_PATTERN.finditer(log_text):
        if len(scenarios) >= MAX_SCENARIOS:
            return scenarios
        if overlaps_consumed(m.start(), m.end()):
            continue
        claim = m.group(1).strip(" :-,.")
        if len(claim) < 10:
            continue
        name_words = claim.split()[:3]
        add(" ".join(name_words), f"verified: {claim}", (m.start(), m.end()))

    # 4. Confidence words — weakest signal, only fills remaining slots.
    for m in CONFIDENCE_PATTERN.finditer(log_text):
        if len(scenarios) >= MAX_SCENARIOS:
            return scenarios
        if overlaps_consumed(m.start(), m.end()):
            continue
        word = m.group(1).strip().lower()
        rest = m.group(2).strip(" :-,.")
        if not rest or len(rest) < 10:
            continue
        claim = f"{word} {rest}"
        name_words = rest.split()[:3]
        add(f"{word}-{' '.join(name_words)}", claim, (m.start(), m.end()))

    return scenarios


def format_block(last_updated: str, last_session_log: str, scenarios: list[dict]) -> str:
    lines = [
        "<!-- status-freshness",
        f"last_updated: \"{last_updated}\"",
        f"last_session_log: \"{last_session_log}\"",
        "verified_scenarios:",
    ]
    if not scenarios:
        lines[-1] = "verified_scenarios: []"
    else:
        for s in scenarios:
            lines.append(f"  - name: \"{_esc(s['name'])}\"")
            lines.append(f"    claim: \"{_esc(s['claim'])}\"")
            lines.append(f"    source: \"{_esc(s['source'])}\"")
            lines.append(f"    date: \"{_esc(s['date'])}\"")
    lines.append("-->")
    return "\n".join(lines) + "\n"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def splice_block(original: str, new_block: str) -> str:
    """Replace existing block or insert after H1. Preserves all other bytes."""
    if BLOCK_RE_SPLICE.search(original):
        # Use a lambda replacement so `\1`, `\g<name>`, etc. inside new_block
        # are NOT interpreted as regex backreferences. Claim text may contain
        # arbitrary characters and a literal `\1` would otherwise corrupt the file.
        return BLOCK_RE_SPLICE.sub(lambda _m: new_block, original, count=1)

    h1 = H1_RE.search(original)
    if h1:
        insert_at = h1.end()
        tail = original[insert_at:]
        lead_blank = re.match(r"\n+", tail)
        skip = lead_blank.end() if lead_blank else 0
        return (
            original[: insert_at + skip]
            + "\n"
            + new_block
            + original[insert_at + skip:]
        )

    return new_block + "\n" + original


def atomic_write(path: str, content: str) -> None:
    """Write via tempfile + os.replace() — safe against crashes mid-write."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(
        prefix=".regen-freshness-",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="vault project slug")
    ap.add_argument("--log", default=None, help="session log date YYYY-MM-DD")
    ap.add_argument("--cwd", default=None, help="override cwd for project detection")
    args = ap.parse_args()

    # Validate --log is a plausible ISO date prefix (guards against path
    # traversal via --log argument).
    if args.log is not None and not ISO_DATE_RE.match(args.log):
        err(f"--log must be YYYY-MM-DD, got: {args.log!r}")
        return 1

    config = load_config()
    if not config:
        err("~/.zaude/config.json not found")
        return 1

    vault_path = os.path.expanduser(config.get("vault_path") or "")
    if not vault_path or not os.path.isdir(vault_path):
        err(f"vault_path invalid: {vault_path!r}")
        return 1

    projects_subdir = config.get("projects_subdir") or "01-projects"
    vault_root = os.path.join(vault_path, projects_subdir)

    project = args.project
    if not project:
        cwd = args.cwd or os.getcwd()
        project = detect_project(cwd, vault_root, config.get("cwd_to_project") or {})
    if not project:
        err("cannot determine project; pass --project SLUG")
        return 1

    vault_dir = os.path.join(vault_root, project)
    if not os.path.isdir(vault_dir):
        err(f"project dir missing: {vault_dir}")
        return 1

    sessions_dir = os.path.join(vault_dir, "sessions")
    log_date = args.log or datetime.date.today().isoformat()
    log_basename = f"{log_date}.md"
    log_path = os.path.join(sessions_dir, log_basename)

    if not os.path.isfile(log_path):
        # Try variants like 2026-04-17-evening.md
        matches = sorted(glob.glob(os.path.join(sessions_dir, f"{log_date}*.md")))
        if matches:
            log_path = matches[-1]
            log_basename = os.path.basename(log_path)
        else:
            err(f"session log for {log_date} not found at {log_path}")
            return 2

    log_text = read_capped(log_path, MAX_LOG_BYTES)
    if not log_text:
        err(f"cannot read session log or empty: {log_path}")
        return 1

    scenarios = extract_scenarios(log_text, log_basename, log_date)
    if not scenarios:
        err(f"no verified claims detected in {log_basename}; writing empty scenarios list")

    state_path = os.path.join(vault_dir, "current-state.md")
    if not os.path.isfile(state_path):
        err(f"current-state.md missing: {state_path}")
        return 1

    original = read_capped(state_path, MAX_LOG_BYTES)
    if not original:
        err(f"cannot read current-state.md or empty: {state_path}")
        return 1

    today_iso = datetime.date.today().isoformat()
    block = format_block(today_iso, f"sessions/{log_basename}", scenarios)
    updated = splice_block(original, block)

    if updated == original:
        err("no change needed (block already up-to-date)")
        return 0

    # Preserve original line endings if file used CRLF uniformly.
    # Heuristic: if every newline in the original was preceded by \r, treat
    # as pure-CRLF and re-emit as CRLF. Otherwise leave as-is (preserves
    # mixed-ending files rather than homogenizing them).
    if original.count("\r\n") > 0 and original.count("\r\n") == original.count("\n"):
        updated = updated.replace("\r\n", "\n").replace("\n", "\r\n")

    try:
        atomic_write(state_path, updated)
    except OSError as exc:
        err(f"cannot write current-state.md: {exc}")
        return 1

    err(
        f"wrote status-freshness block: last_updated={today_iso}, "
        f"last_session_log=sessions/{log_basename}, scenarios={len(scenarios)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
