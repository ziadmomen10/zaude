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
8. **Check GitHub for vault drift** before pushing: `git fetch origin && git status -sb` in the vault. If the remote has newer commits, STOP and ask the user to reconcile — never force-push.
9. **Commit the vault** with message: `session $(date +%F): <short summary>`
10. **Push the vault** to GitHub
11. **Confirm final state** — run `git status` on both the project repo and the vault, report both are clean (or report exactly what's dirty and why it was left that way).

## Gates

- If `code-reviewer` returns CRITICAL or HIGH findings on uncommitted work, STOP and tell the user before touching the vault.
- If the vault has unrelated uncommitted changes (from another project), do NOT bundle them — commit only `01-projects/<current project>/` and any shared `03-patterns/` changes.
- If the push to the vault is rejected because the remote has newer commits, STOP — do NOT force-push. Ask the user to reconcile.
- Tokens don't matter — never skip a step or a scan to save context. This includes the memory sweep (step 6) and credential scan (step 7); always run both even if the session felt light.
