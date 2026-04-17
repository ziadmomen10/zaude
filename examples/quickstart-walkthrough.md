# Quickstart Walkthrough — Zaude by Example

A step-by-step walkthrough using the example project at [`./example-project/`](./example-project/). Read the files in that directory alongside this walkthrough to see Zaude's conventions applied to a realistic codebase.

---

## What you'll see

The `example-project/` directory mirrors a real Zaude-managed project vault:

```
example-project/
├── CLAUDE.md              ← project-specific rules and constraints
├── current-state.md       ← where the project is right now
├── decisions.md           ← 4 real-looking architectural decisions
├── open-questions.md      ← 6 open questions at various severities
├── spec.md                ← the project specification
├── architecture.md        ← system design with Mermaid diagrams
└── sessions/
    └── 2026-04-16.md      ← a realistic session log
```

This is **notekit**, a fictional local-first Markdown notes app. The content isn't important — what matters is the shape.

---

## Read the files in this order

To understand how a Zaude vault evolves in practice, read these in sequence:

### 1. [CLAUDE.md](./example-project/CLAUDE.md) — project instructions

Short, authoritative, specific. Notice:

- What the project IS (first paragraph)
- The exact stack (no vague descriptions like "React app" — names + versions)
- Hard rules with rationale
- Explicit "Claude can freely touch / must not touch" sections
- A session-start checklist

Your own `CLAUDE.md` should be equally concrete.

### 2. [spec.md](./example-project/spec.md) — what the project is

Separates **in-scope** from **out-of-scope** explicitly. Notice the success criteria are measurable (frame time < 16ms, 100 users for 30+ days), not vague.

### 3. [architecture.md](./example-project/architecture.md) — how it's built

Mermaid diagrams for system overview and data model. Key flows described step-by-step. External dependencies called out with their failure modes ("Without it, X stops; Y continues").

### 4. [decisions.md](./example-project/decisions.md) — why choices were made

Four decisions from the first 6 days of the project. Notice the format:
- Date + one-line title
- **Decision:** what you decided
- **Rationale:** why THIS, naming the constraints
- **Implications:** what this changes for future work

The 2026-04-16 entry ("Promote to production only after conflict UI ships") is a decision that came out of a review gate — the architect-review flagged the conflict behavior as HIGH, which triggered the decision to delay promotion.

### 5. [open-questions.md](./example-project/open-questions.md) — unresolved items

Six questions at CRITICAL / HIGH / MEDIUM / LOW / deferred severities. One is already resolved (Q2 — Turso cost). Notice:
- Numbered sequentially, never renumbered
- Resolved questions stay in place with `— RESOLVED YYYY-MM-DD`
- Each question has options with effort estimates and a **Recommended** pick

### 6. [current-state.md](./example-project/current-state.md) — where things stand

Overwritten every session. Notice what it captures:
- Status paragraph (commit count, recent hash, what's deployed, what's blocking)
- What exists / what's in flight / known issues — three separate sections
- **Next action** — single most important thing to do next session
- **Last session** + optional **Previous session** for quick context

### 7. [sessions/2026-04-16.md](./example-project/sessions/2026-04-16.md) — a session log

Shows the full `/wrap` or `/ship` output: summary, commits, decisions, lessons, credentials to rotate. These accumulate over time and form the project's history.

---

## How this vault was built (session by session)

Imagine watching a time-lapse of this vault:

**Day 1 (2026-04-10):** Project scaffolded. `CLAUDE.md` and `spec.md` written. First decision appended ("Local-first with Turso sync"). First `/wrap` produces `sessions/2026-04-10.md`.

**Day 2 (2026-04-12):** Auth design session. Magic-link decision appended. `current-state.md` updated. Session log added.

**Day 4 (2026-04-14):** Storage format locked (Markdown). `architecture.md` filled in with the data model Mermaid diagram. Open question Q1 (secrets in notes) filed.

**Day 6 (2026-04-16):** v0.4.0 ships to staging. Sync engine optimized. Architect-review catches the conflict silent-loss; decision appended, Q6 filed. v0.4.0 does NOT promote to production — it waits for the conflict UI.

**Day 7 (today):** SessionStart hook loads all of the above into Claude's context. You ask `/start` and get an immediate, accurate report of where to pick up.

---

## Try it

1. Install Zaude (see [`../install/setup-prompt.md`](../install/setup-prompt.md)).
2. Copy the `example-project/` directory into your new vault's `01-projects/` folder as `notekit` (or any name).
3. Add `{"notekit": "notekit"}` to `cwd_to_project` in `~/.zaude/config.json` (adjust the cwd basename to match).
4. Open a new Claude Code session in a folder named `notekit` somewhere.
5. The initial system reminder should contain `=== VAULT CONTEXT FOR notekit ===` with all the files from this example loaded.
6. Type `/start` — Claude will read the loaded context and tell you where to pick up.

---

## See also

- [docs/04-vault.md](../docs/04-vault.md) — vault pattern deep-dive
- [docs/10-workflow.md](../docs/10-workflow.md) — session lifecycle walkthrough
- [docs/11-best-practices.md](../docs/11-best-practices.md) — philosophy and do's/don'ts
