# <Project Name> — Decisions

**Append-only.** Never edit past entries. To reverse a decision, add a new entry explaining the reversal.

Loaded in full by the `SessionStart` hook — no rotation, no archiving, no line-count limit. If authoring this file ever gets tedious, split on a natural quarter boundary (e.g. `decisions-2026-Q1.md`) and the hook will still read both.

---

## YYYY-MM-DD — Example decision title

**Decision:** One paragraph describing what you decided.

**Rationale:** Why this, not the alternatives. Name the constraints that forced this choice.

**Implications:** What this means for future work. What it blocks, unblocks, or changes downstream.
