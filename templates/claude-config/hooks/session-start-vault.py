#!/usr/bin/env python3
"""Zaude — SessionStart hook.

Loads the current project's full vault context as `additionalContext` so
Claude Code sees everything it needs on the first token of every session:
- Project vault: CLAUDE.md, current-state.md, decisions.md + archives,
  open-questions.md, spec.md, architecture.md
- Recent session logs (last N, configurable)
- Cross-project patterns directory
- Local memory files (feedback/user/project/reference types)

Configuration is read from ~/.zaude/config.json. If the file is missing
or invalid, the hook silently exits with {} — never blocks session start.

Config schema:
{
  "vault_path": "/home/user/zaude-vault",
  "patterns_subdir": "03-patterns",
  "projects_subdir": "01-projects",
  "cwd_to_project": {"CwdBasename": "vault-project-slug"},
  "recent_session_logs": 3,
  "claude_config_path": "/home/user/.claude"
}
"""
import glob
import json
import os
import sys


def load_config() -> dict:
    path = os.path.expanduser("~/.zaude/config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def detect_project(cwd: str, vault_root: str, cwd_map: dict) -> str | None:
    """Walk up from cwd looking for a folder that matches a vault project.
    Checks the explicit cwd→project map first, then falls back to a
    literal basename match against vault subdirs."""
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


def find_memory_dir(cwd: str, claude_config_path: str) -> str | None:
    """Find ~/.claude/projects/<encoded-cwd>/memory/ by substring match.
    Claude Code encodes cwd in the directory name; the last path segment
    of cwd is a reliable substring."""
    projects_root = os.path.join(claude_config_path, "projects")
    if not os.path.isdir(projects_root):
        return None
    normalized_cwd = cwd.replace("/", "\\").rstrip("\\")
    last = os.path.basename(normalized_cwd)
    if not last:
        return None
    for entry in os.listdir(projects_root):
        candidate = os.path.join(projects_root, entry, "memory")
        if os.path.isdir(candidate) and last in entry:
            return candidate
    return None


def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def dump_section(title: str, path: str) -> str:
    body = read_file(path)
    if not body:
        return ""
    return f"\n## {title}\n\n{body}\n"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("{}")
        return 0

    cwd = data.get("cwd") or ""
    if not cwd:
        print("{}")
        return 0

    config = load_config()
    if not config:
        print("{}")
        return 0

    vault_path = os.path.expanduser(config.get("vault_path") or "")
    if not vault_path or not os.path.isdir(vault_path):
        print("{}")
        return 0

    projects_subdir = config.get("projects_subdir") or "01-projects"
    patterns_subdir = config.get("patterns_subdir") or "03-patterns"
    recent_session_logs = int(config.get("recent_session_logs") or 3)
    claude_config_path = os.path.expanduser(
        config.get("claude_config_path") or "~/.claude"
    )
    cwd_map = config.get("cwd_to_project") or {}

    vault_root = os.path.join(vault_path, projects_subdir)
    patterns_root = os.path.join(vault_path, patterns_subdir)

    project = detect_project(cwd, vault_root, cwd_map)
    if not project:
        print("{}")
        return 0

    vault_dir = os.path.join(vault_root, project)
    parts: list[str] = [f"=== VAULT CONTEXT FOR {project} ==="]

    # Core vault files (fixed names)
    for filename, title in [
        ("CLAUDE.md", "CLAUDE.md"),
        ("current-state.md", "current-state.md"),
        ("open-questions.md", "open-questions.md"),
        ("spec.md", "spec.md"),
        ("architecture.md", "architecture.md"),
        ("decisions.md", "decisions.md"),
    ]:
        section = dump_section(title, os.path.join(vault_dir, filename))
        if section:
            parts.append(section)

    # Decision archives (pattern match)
    for archive in sorted(glob.glob(os.path.join(vault_dir, "decisions-archive-*.md"))):
        parts.append(dump_section(os.path.basename(archive), archive))

    # Recent session logs
    sessions_dir = os.path.join(vault_dir, "sessions")
    if os.path.isdir(sessions_dir):
        session_files = sorted(
            glob.glob(os.path.join(sessions_dir, "*.md")),
            reverse=True,
        )[:recent_session_logs]
        for session_path in reversed(session_files):
            parts.append(
                dump_section(
                    f"session log {os.path.basename(session_path)}",
                    session_path,
                )
            )

    # Cross-project patterns
    if os.path.isdir(patterns_root):
        for pattern_file in sorted(glob.glob(os.path.join(patterns_root, "*.md"))):
            parts.append(
                dump_section(
                    f"pattern: {os.path.basename(pattern_file)}",
                    pattern_file,
                )
            )

    # Local memory
    memory_dir = find_memory_dir(cwd, claude_config_path)
    if memory_dir:
        index_path = os.path.join(memory_dir, "MEMORY.md")
        if os.path.isfile(index_path):
            parts.append(dump_section("MEMORY.md (index)", index_path))
        for memory_file in sorted(glob.glob(os.path.join(memory_dir, "*.md"))):
            if os.path.basename(memory_file) == "MEMORY.md":
                continue
            parts.append(
                dump_section(
                    f"memory: {os.path.basename(memory_file)}",
                    memory_file,
                )
            )

    if len(parts) == 1:
        print("{}")
        return 0

    context = "\n".join(parts)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
