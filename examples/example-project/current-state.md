# notekit — Current State

**What's in flight right now.** Overwritten at each `/wrap` or `/ship`.

---

## Status

**47 commits on main (`a3f92c1`). v0.4.0 shipped to staging 2026-04-16 — magic-link auth works end-to-end, sync engine down to 180ms p95 for 1000-note workspaces. Currently finishing the conflict-resolution UI before promoting to production.**

---

## What exists

- **Editor:** Monaco-based Markdown editor with live preview, custom footnote syntax, drag-and-drop attachments
- **Auth:** magic link via Resend, JWT with httpOnly refresh cookie, session audit log
- **Sync:** Turso replica per user, optimistic local writes, conflict detection on write-time
- **Backend:** Hono routes for `/notes`, `/auth`, `/sync`; rate-limited to 100 req/min/user
- **Tests:** 143 unit + 31 integration, all green

---

## In-flight work

- **Conflict-resolution UI** — backend detects conflicts correctly but the frontend currently just picks the local copy silently. Building a 3-way merge view. ~4 hours remaining.
- **Keyboard shortcut audit** — Cmd+K, Cmd+P, Cmd+S all work; Cmd+Shift+F search-in-workspace half-wired.

---

## Known issues / next session

- Notes with >10k lines cause editor lag (tracked as Q3, HIGH)
- Export-to-PDF rounds emoji widths incorrectly on Windows (Q5, MEDIUM)
- Database migration `0007_add_tags.sql` needs a rollback plan before prod (Q6, MEDIUM)

---

## Next action

**Finish conflict-resolution UI.** Component scaffold is at `src/features/sync/ConflictView.tsx`, needs the merge-action dispatch wired to the backend. Then `/ship` and promote to production.

---

## Blocked on

Nothing. Conflict UI unblocks production promotion; once that ships v0.4.0 is done.

---

## Last session

**2026-04-16** — v0.4.0 shipped to staging. Magic-link auth end-to-end tested, sync engine p95 benchmarked against a 1000-note synthetic workspace. Filed Q6 (migration rollback plan) after architect-review flagged the risk of breaking live staging if the tags table needs reverting.

---

## Previous session

**2026-04-15** — Magic-link auth integration. Resend API wired, email templates done, rate-limiting on `/auth/magic-link`, session replay test passing.
