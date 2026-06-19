Report where we left off on the current project. Do NOT re-read the vault from disk — the `SessionStart` hook at `~/.claude/hooks/session-start-vault.py` has already injected the full vault context (CLAUDE.md, current-state.md, decisions.md + archives, open-questions.md, spec.md, architecture.md, last 3 session logs, cross-project patterns, and all memory files) before this skill runs.

> **Zaude v2 check.** If this repo has a `.zaude/` directory, the injected v1 vault may be stale (in v2 the signed trace is the source of truth). Prefer **`/zstart`**, which reports the current state rebuilt from the trace, and treat the v1 `current-state.md` as informational only.

## If the hook didn't inject context

Rare but possible: the cwd wasn't recognized as a known project, or the hook config is wrong. Symptom: the system reminder at session start does NOT contain `=== VAULT CONTEXT FOR <project> ===`.

Recovery: tell the user the hook did not fire for this cwd, point at `cwd_to_project` in `~/.zaude/config.json`, and ask which vault project to load. Do NOT silently fall through to reading files one by one — the hook's job is to be the single mechanical loader.

## Normal flow — just report

Pull the following from the vault context already in your window and report:

- **Last session summary** — one paragraph of what shipped most recently (from the latest session log + `current-state.md`).
- **In-flight work** — anything flagged "what's in flight" or "known issues" in `current-state.md`.
- **Blocking issues** — anything in `open-questions.md` flagged as unresolved (CRITICAL/HIGH with no resolution note) or listed in `current-state.md` as "blocked on".
- **Active memory rules** — one-line summary of each `feedback_*.md` memory file so the user sees what behaviors are in force.
- **Next concrete action** — from `current-state.md` "Next action" section.

## On-demand reads

The hook deliberately caps session-log loads at the 3 most recent (configurable via `recent_session_logs` in `~/.zaude/config.json`). If the user's first question points at an older session, open the relevant older `sessions/YYYY-MM-DD.md` directly. Same for any archived file not covered by the hook.

## Then wait

Do NOT start building. Wait for the user's explicit instruction after the report.
