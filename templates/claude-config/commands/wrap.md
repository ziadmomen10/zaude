End-of-session wrap-up. Leaves both the project repo and the vault in a clean, documented state.

## Steps

1. **Run `code-reviewer`** one final time on any uncommitted changes in the current repo. Report findings. Do NOT fix anything — if CRITICAL or HIGH, stop and tell the user to decide.
2. **Update `$VAULT/01-projects/<current project>/current-state.md`**:
   - Refresh the "Status" line with current commit count / latest commit hash / what exists
   - Update "Known issues" with anything discovered this session
   - Update "Next action" to reflect the new starting point
   - Mark any completed in-flight items as done
3. **Write or append to `$VAULT/01-projects/<current project>/sessions/YYYY-MM-DD.md`**:
   - One-paragraph session summary
   - Commits shipped (hash + one-line message)
   - Key decisions made
   - Lessons learned or corrections (especially user feedback that changed direction)
   - Credentials exposed for rotation
4. **Append any new decisions** to `decisions.md`. Each entry: date, one-line decision, rationale paragraph, implications. No rotation or archiving — the `SessionStart` hook reads the whole file every session, so a long file is not a problem. If the file ever gets unwieldy to author in, split on a natural quarter boundary (`decisions-2026-Q1.md`), not a line count.
5. **Append any new open questions** to `open-questions.md`. Number sequentially (QN) using the template at the bottom of the file.
6. **Persist any new feedback memory from this session** into `~/.claude/projects/<encoded-cwd>/memory/`:
   - Scan the conversation for: corrections the user gave ("don't", "stop", "no not that"), approach validations ("yes exactly", "keep doing that"), new project facts with a **why**, or pointers to external systems.
   - For each, create or update a dedicated `.md` file following the memory frontmatter format and add/update the pointer in `MEMORY.md`.
   - Auto-memory fires in real-time during the session too — this is a final sweep to catch anything that slipped through.
7. **List credentials exposed this session** that need rotation:
   - Scan the conversation for pasted passwords, API keys, tokens, SSH keys
   - Report the first 4 and last 4 characters only, never the full value
   - Note which service each credential belongs to
8. **Regenerate the status-freshness block** — run `python ~/.claude/hooks/lib/regen-freshness.py` from the session's cwd. This mechanically parses today's session log for verified claims (`X/Y` ratios, `verified:` markers, `[x] verified:` checklist items, confidence words like `shipped` / `end-to-end` / `green`) and rewrites the `<!-- status-freshness -->` block at the top of `current-state.md`. If the session log doesn't exist yet, step 3 must have created it first.
9. **Gate: validate the freshness block** — run `FRESHNESS_ENFORCE=1 python ~/.claude/hooks/current-state-freshness.py --check --cwd "$(pwd)"`. If exit code is non-zero, STOP — the block is missing/stale/malformed. The validator's stderr tells you exactly what to fix; usually re-run step 8. Do NOT commit the vault until this check passes. This is the actual gate, not the SessionEnd hook — Claude Code's SessionEnd events cannot block the session from committing, so the gate lives here in `/wrap`.
10. **Check GitHub for vault drift** before pushing: `git fetch origin && git status -sb` in the vault. If the remote has newer commits, STOP and ask the user to reconcile — never force-push.
11. **Commit the vault** with message: `session $(date +%F): <short summary>`
12. **Push the vault** to GitHub
13. **Confirm final state** — run `git status` on both the project repo and the vault, report both are clean (or report exactly what's dirty and why it was left that way).

## Gates

- If `code-reviewer` returns CRITICAL or HIGH findings on uncommitted work, STOP and tell the user before touching the vault.
- If the vault has unrelated uncommitted changes (from another project), do NOT bundle them — commit only `01-projects/<current project>/` and any shared `03-patterns/` changes.
- If the push to the vault is rejected because the remote has newer commits, STOP — do NOT force-push. Ask the user to reconcile.
- Tokens don't matter — never skip a step or a scan to save context. This includes the memory sweep (step 6) and credential scan (step 7); always run both even if the session felt light.

## Agent dispatch — single source of truth

Step 1's `code-reviewer` pass extends per the v0.5 dispatch matrix in `03-patterns/agent-usage.md`. When uncommitted work touches Python hooks, `python-pro-readonly` fires alongside `code-reviewer`. When it touches skill/agent `.md` files, `prompt-engineer-readonly` fires. When docs are >50% of the diff, `documentation-engineer-readonly` fires. All `-readonly` variants — `/wrap` remains read-only on the project repo.
