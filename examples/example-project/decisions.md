# notekit — Decisions

**Append-only.** Never edit past entries.

---

## 2026-04-10 — Local-first with Turso sync, not backend-first

**Decision:** SQLite on the client is the source of truth. The backend is a sync server, not a primary database. Writes hit local SQLite first; sync to Turso happens in the background.

**Rationale:** Two design constraints forced this. First, the product demands offline-first editing — notes must be writable without a network. Second, response times for text editing must be < 16ms (one frame at 60fps), which rules out any design that waits on a network round-trip. Local-first SQLite solves both. Turso was picked over a self-rolled sync server because its replica model maps cleanly onto the "one replica per user" pattern we need.

**Implications:**
- Every write path must work offline. No "save to cloud" button that can fail.
- Conflict resolution happens at sync-time on the client, not at write-time on the server.
- Testing story requires a sync harness that simulates network partitions.
- We cannot trust the server copy when reconciling conflicts — the client's vector clock wins for recent edits.

---

## 2026-04-12 — Magic-link auth, not passwords

**Decision:** Users authenticate via email magic links (one-time codes sent via Resend). No password field anywhere in the product. Sessions are JWT + httpOnly refresh cookie.

**Rationale:** Passwords are a liability we don't want. Password reset flows, breach notifications, credential stuffing defenses — all of it is infrastructure we'd have to build and maintain for a single-user note-taking app where the threat model is "someone guesses your password." Magic links shift the trust boundary to email, which the user is already managing. Resend gives us transactional delivery with zero infra cost below 3000 emails/month.

**Implications:**
- Email deliverability becomes a production concern. SPF/DKIM/DMARC are now hard requirements.
- No "forgot password" flow — instead the magic-link flow IS the recovery flow.
- Rate-limiting on `/auth/magic-link` is non-optional (we ship with 5/15min/IP).
- If Resend outages happen, users literally cannot log in. Document this tradeoff; consider a secondary provider when MRR justifies the complexity.

---

## 2026-04-14 — Markdown as storage format, not a custom binary

**Decision:** Every note is stored as a plain `.md` file on disk (or equivalent row in SQLite with a `body TEXT` column). No custom binary format, no JSON AST, no proprietary schema.

**Rationale:** We considered a structured AST format for richer features (embedded drawings, typed blocks, etc.) but rejected it for three reasons: (1) plain Markdown is readable with any text editor, protecting users from lock-in; (2) the sync format is trivially human-diffable, which is critical for conflict resolution; (3) the feature premium of a custom AST doesn't justify the user-hostile lock-in — users can already embed images, code blocks, and tables in standard Markdown.

**Implications:**
- Export is free: copying the SQLite file's `body` columns to `.md` files on disk is a three-line script.
- Features that would require structured storage (typed blocks, embedded queries) are out of scope for v1.
- Third-party Markdown editors can edit our files directly — users can leave notekit anytime.

---

## 2026-04-16 — Promote to production only after conflict-resolution UI ships

**Decision:** v0.4.0 stays on staging until the conflict-resolution UI is complete. Users hitting a conflict today get silent local-wins; that's unacceptable for production.

**Rationale:** Architect-review flagged the silent conflict behavior as HIGH during 2026-04-16 ship review. Promoting now would mean shipping a product that can silently lose remote edits. The conflict-resolution UI is ~4 hours of work; delaying the promotion by one session is the right trade.

**Implications:**
- Production stays on v0.3.2 until conflict UI ships.
- The production promotion workflow (`/ship`, merge to `release` branch) gates on conflict UI being mentioned in the CHANGELOG for v0.4.0.
- Staging continues to receive every push to `main` so we get early signal.
