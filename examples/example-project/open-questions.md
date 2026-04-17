# notekit — Open Questions

Numbered, append-only. Mark as resolved in place; don't renumber.

---

## Q1 — How do we handle notes that contain secrets? (MEDIUM)

**What:** Users will inevitably paste API keys, tokens, and other secrets into notes. Should the app warn them, detect patterns, or offer encryption-at-rest?

**Why it matters:** One breach of the Turso replica could leak every user's pasted credentials. The local-first model protects against most threats but not from Turso-side compromise.

**Options:**
1. Pattern-detect common secret formats (AWS keys, `sk-*`, JWTs) and show an in-editor warning. Low effort (~4 hr). Doesn't prevent leaks, just nudges.
2. Per-note encryption at rest with a user-supplied passphrase. High effort (~2 days). Solves the Turso-compromise case but makes search across encrypted notes impossible.
3. Do nothing. Acceptable for v1 if we document the threat model clearly.

**Recommended:** Option 1 for v1, option 2 after 1,000 paying users or a real incident.

---

## Q2 — Turso replica cost at 10k users — RESOLVED 2026-04-13

**What:** How does Turso pricing scale with our "one replica per user" design?

**Resolved:** Tested with 500 synthetic replicas, each with 1000 notes (~50MB each). Turso bills per replica-hour + storage; at 10k users the bill is ~$400/month. Acceptable within our unit economics. Will revisit if we pass 50k users.

---

## Q3 — Editor lag on 10k+ line notes (HIGH)

**What:** Monaco editor becomes noticeably sluggish when editing a single note over ~10,000 lines.

**Why it matters:** Power users will hit this. It'll show up in benchmarks. Our "fast editing" value prop degrades.

**Options:**
1. Switch to CodeMirror 6 — better performance at scale, smaller bundle. Migration cost: ~2 days.
2. Virtualize the Monaco viewport ourselves — ~1 day, fragile.
3. Soft-cap notes at 5000 lines with a "split this note" suggestion. ~2 hours, annoying.

**Recommended:** Option 1 when we confirm more than ~5% of users hit the lag. Until then, option 3 as a soft warning.

---

## Q4 — Do we support end-to-end encryption in v2? (LOW, deferred)

**What:** Some users will want E2E encryption so not even our server can read their notes.

**Why it matters:** Competitive positioning ("zero-knowledge") + hard privacy guarantees.

**Options:**
1. Ship E2E with passphrase-derived keys. Breaks server-side search, breaks collaborative editing, breaks export-to-HTML.
2. Add optional per-workspace encryption flag. Users opt in; we advertise it.
3. Stay unencrypted; lean on our no-telemetry policy and minimal data collection instead.

**Recommended:** Deferred until after v1 ships. Too much product-shape impact to decide early.

---

## Q5 — PDF export emoji widths on Windows (MEDIUM)

**What:** Export-to-PDF pipeline (Puppeteer in CI) renders emoji using a fallback font on Windows workers, causing width miscalculations and broken line-wrapping.

**Why it matters:** Blocks a power-user feature for Windows-based Turso replica hosts.

**Options:**
1. Bundle Noto Emoji into the PDF template. ~1 hr. Solves.
2. Tell Windows users to use Linux workers. Ugly, but works.

**Recommended:** Option 1.

---

## Q6 — Migration 0007 (add_tags table) needs a rollback plan before production (MEDIUM)

**What:** The `tags` table migration introduces a NOT NULL foreign key to `notes`. If we need to revert after live users have tag data, plain `DROP TABLE` would lose data.

**Why it matters:** Architect-review flagged this during 2026-04-16 ship review. Reverting a breaking schema change after users have data is painful.

**Options:**
1. Document a reverse migration `0007_down.sql` that exports tag data to a JSON sidecar before drop.
2. Make the FK nullable so `DROP TABLE tags` doesn't cascade; accept orphan state.
3. Commit to not reverting; add integration tests that catch regressions instead.

**Recommended:** Option 1 before promoting to production.

---

## Format for new questions

```markdown
## QN — Short title (SEVERITY)

**What:**

**Why it matters:**

**Options:**
1.
2.

**Recommended:**
```

Severity: CRITICAL / HIGH / MEDIUM / LOW / deferred.
