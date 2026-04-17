# Vault Protocol — How Zaude Reads This Vault

This file defines the reading order and update discipline for every session. The `SessionStart` hook and slash commands (`/start`, `/wrap`, `/ship`) enforce it.

---

## Directory layout

```
vault-root/
├── VAULT_PROTOCOL.md           ← this file (reading order + conventions)
├── 01-projects/                ← one subdirectory per project
│   └── <project-slug>/
│       ├── CLAUDE.md           ← project-specific instructions
│       ├── current-state.md    ← what's built, what's broken, last state
│       ├── decisions.md        ← append-only decision log
│       ├── open-questions.md   ← unresolved items, numbered Q1, Q2, …
│       ├── spec.md             ← project spec (optional)
│       ├── architecture.md     ← architecture doc (optional)
│       └── sessions/
│           └── YYYY-MM-DD.md   ← per-session work log
├── 03-patterns/                ← cross-project rules
│   ├── anti-patterns.md        ← lessons from real failures
│   └── credential-handling.md  ← credential rules
└── (optional) 04-knowledge/    ← reference material
```

---

## SessionStart — reading order

The `SessionStart` hook loads all of the following automatically as `additionalContext`:

1. `01-projects/<project>/CLAUDE.md`
2. `01-projects/<project>/current-state.md`
3. `01-projects/<project>/open-questions.md`
4. `01-projects/<project>/spec.md`
5. `01-projects/<project>/architecture.md`
6. `01-projects/<project>/decisions.md` (including any `decisions-archive-*.md`)
7. Last N session logs (default 3, configurable)
8. Every `.md` in `03-patterns/`
9. Every `.md` in the local memory directory

Projects are detected by matching the cwd basename to a folder under `01-projects/`, with optional overrides in `~/.zaude/config.json` `cwd_to_project`.

---

## SessionEnd — update discipline

Run `/wrap` or `/ship`. These commands:

1. Run code review on uncommitted work.
2. Overwrite `current-state.md` with the new state.
3. Append a session log at `sessions/YYYY-MM-DD.md`.
4. Append any new decisions to `decisions.md` (append-only — never edit past entries).
5. Append any new open questions to `open-questions.md`.
6. Sweep the conversation for corrections/validations → persist to memory files.
7. List credentials that need rotation.
8. Commit and push the vault.

---

## Append-only discipline

- **`decisions.md`** — append-only. Reverse a past decision by adding a new entry that explains the shift.
- **`sessions/*.md`** — never edit a previous day's log. Each file is immutable after the day closes.
- **`open-questions.md`** — questions get numbered sequentially. Resolution is marked in place by appending `— RESOLVED YYYY-MM-DD` to the heading; don't delete or renumber.
- **`current-state.md`** — freely overwritten. It's a current snapshot, not history.

---

## Decision entry format

```markdown
## YYYY-MM-DD — One-line decision title

**Decision:** One paragraph describing what you decided.

**Rationale:** Why this, not the alternatives. Name the constraints that forced it.

**Implications:** What this means for future work. What it blocks / unblocks / changes downstream.
```

---

## Session log format

```markdown
# YYYY-MM-DD — Short title

## Summary
One paragraph.

## Commits shipped
- `abc1234` — short description

## Key decisions
- (Mirror of entries appended to decisions.md)

## Lessons / corrections
- (Anything the user corrected or validated)

## Credentials exposed
- (Anything to rotate, shown first-4 / last-4 only)
```

---

## Open-question entry format

```markdown
## Q<N> — Short title (SEVERITY)

**What:** One sentence.
**Why it matters:** Who's blocked / what breaks.
**Options:** Numbered list of resolution paths.
**Recommended:** The one to pick and why.
```

Severity: CRITICAL, HIGH, MEDIUM, LOW, deferred.

---

## Memory lives in `~/.claude/projects/<encoded-cwd>/memory/`

Not in the vault. Memory is cwd-keyed and machine-local. Four types: `feedback_*.md` (how to behave), `project_*.md` (project facts), `user_*.md` (user profile), `reference_*.md` (external-system pointers). Indexed in `MEMORY.md`.

If you back up your Claude-config directory as a separate repo (recommended), memory files travel with it.
