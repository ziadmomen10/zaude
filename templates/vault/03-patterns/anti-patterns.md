# Anti-Patterns — Cross-Project Rules

Rules distilled from real failures. These apply to all projects unless a project's `CLAUDE.md` overrides one.

Loaded by the `SessionStart` hook on every session.

---

## Rule 1 — Hooks for enforcement, skills for suggestions

**Problem:** A slash-command skill that says "read these 6 files" is a suggestion Claude can silently fail to follow. Files added later won't be read.

**The rule:** When you need a "never happen again" guarantee, put the logic in a Claude Code hook (`SessionStart`, `PreToolUse`, `SessionEnd`). Hooks are enforced by the harness. Skills are fine for workflow documentation — just don't rely on them for mechanical enforcement.

**When it applies:** Auto-loading context, auto-committing on session end, blocking writes to frozen paths, anything the user expects to happen 100% of the time.

---

## Rule 2 — Use slash commands, not memorized phrases

**Problem:** Manual prompting ("read the vault", "run the review chain", "commit and push") is slower, skip-prone, and inconsistent across sessions.

**The rule:** `/start`, `/build`, `/review`, `/ship`, `/wrap` are the workflow. Manual prompting is fallback only. If a slash command covers the workflow, use it so the review chain runs automatically.

---

## Rule 3 — Design before review, not after

**Problem:** Running `architect-review` only as a post-hoc REVIEW catches structural issues but fixing them after the fact costs 3–5x more than designing correctly upfront.

**The rule:** For any new service, route, middleware, schema table, or major component, invoke `architect-review` in DESIGN mode BEFORE writing code. Describe the intent, ask for the pattern, then build it. Run REVIEW mode after for coverage.

---

## Rule 4 — Credentials pasted inline are ephemeral

**Problem:** Credentials pasted into chat get echoed into logs, vault files, commit messages, and bug reports. Rotating after the fact is painful.

**The rule:** When a credential is pasted, use it and forget it. Never write it to a vault file, a repo, a commit message, or an audit log. At `/wrap`, list which credentials were exposed this session so they can be rotated. Reference them in text as first-4 / last-4 only.

---

## Rule 5 — No mock data, no placeholders, no hardcoded fallbacks

**Problem:** Placeholder data ("John Doe", `TODO: replace`, fake IDs) hides real bugs. The UI looks fine until real data arrives and breaks it.

**The rule:** Every value must come from a real source. If the source is missing, render empty state — not fake data. If you need to demo something, use a real example record from the dev database.

---

## Rule 6 — Root-cause-first remediation

**Problem:** Quick fixes (silence an error, retry, add a null check) paper over real bugs. The real bug resurfaces elsewhere a week later.

**The rule:** Find the root cause before patching symptoms. "It works now" without knowing why is a failure. If the root cause requires a bigger fix than you have time for, ship the symptomatic patch AND file an open question (Q) describing the real fix.

---

## Rule 7 — Don't modify working code outside the task

**Problem:** "While I was in there, I also fixed X" — X silently changes behavior, tests don't cover the new path, a bug ships.

**The rule:** Only touch files the current task actually needs. If you notice a problem in adjacent code, mention it in the report — don't silently fix it. If the fix genuinely belongs in this PR, pull it into the task scope explicitly and add it to the commit message.

---

## Format for new anti-patterns

Copy this template at the bottom of the file. Keep them short — each one should fit on a laptop screen.

```markdown
## Rule N — Short title

**Problem:** What fails if you don't follow this.

**The rule:** What to do instead. Specific and actionable.

**When it applies:** (optional) Trigger conditions.
```
