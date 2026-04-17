Complete the shipping workflow: review → commit → push → vault update. Stops at the first CRITICAL or HIGH finding.

## Steps

1. **Run the full review chain** (equivalent to `/review`):
   - `code-reviewer` on the diff
   - `architect-review` REVIEW mode on structural changes
   - `security-auditor` if auth/crypto/credentials/SSH/input validation is involved
2. **If any CRITICAL or HIGH findings**, STOP. Report them organized by severity and severity and do NOT proceed. The user must fix or explicitly override.
3. **If clean**, commit the changes:
   - Draft a commit message summarizing the change (1-2 sentences, focus on "why")
   - Reference any finding IDs if reviewers left MEDIUM/LOW notes that were accepted as-is
   - Co-authored-by line per CLAUDE.md global rules
4. **Push to main** (`git push`)
5. **Update `$VAULT/01-projects/<current project>/current-state.md`** with:
   - New commit hash
   - What shipped (one paragraph)
   - Any new known issues or next-session starting points
6. **Append to `$VAULT/01-projects/<current project>/sessions/YYYY-MM-DD.md`**:
   - Date-stamped entry of what was shipped in this workflow run
7. **Append any new decisions to `decisions.md`** if this ship represents a notable architectural choice. No rotation or archiving — the `SessionStart` hook reads the whole file every session.
8. **Commit and push the vault** with message: `session YYYY-MM-DD: <short summary>`. Before pushing, `git fetch origin` on the vault and STOP if the remote has newer commits — never force-push the vault.
9. **Report final commit hashes** for both repos
10. **List any credentials exposed this session** that should be rotated (scan the conversation for pasted credentials, API keys, passwords, tokens; report first 4 + last 4 chars only)

## Gates

- Reviewer CRITICAL or HIGH → stop, do NOT commit
- Commit failed pre-commit hook → stop, do NOT bypass with `--no-verify`
- Push rejected (remote has newer commits) → stop, report, do NOT force-push to main
- Vault has unrelated uncommitted changes → stop, report, do NOT bundle them into this commit

Never skip hooks. Never force-push to main. Never bundle unrelated work.
