# Credential Handling

Rules for any secret, password, API key, token, SSH key, or credential that passes through a Claude Code session.

---

## Prime directive

**Credentials pasted into chat are ephemeral. Use them and forget them.**

- Never write a full credential into a vault file, repo, commit message, audit log, or session log.
- Never echo a full credential in a response.
- When referencing a credential in text, show first-4 and last-4 characters only (e.g. `ghp_****…****a1b2`).

---

## At session end

`/wrap` must scan the conversation and list every credential the user pasted. Format:

```
## Credentials exposed this session

- **Anthropic API key** — `sk-a****…****z1`. Rotate at console.anthropic.com.
- **GitHub PAT** — `ghp_****…****a1b2`. Rotate at github.com/settings/tokens.
- **SSH private key** — 512 bytes starting `-----BEGIN OPENSSH`. Rotate by regenerating the key pair on the server and updating your local copy.
```

Group by service, note where to rotate each, never the full value.

---

## Storage patterns that are OK

- `.env` files at project root, gitignored (never committed)
- Platform-native secret stores (GitHub Actions secrets, AWS SSM, Vercel env vars)
- Password managers (1Password, Bitwarden, etc.)
- Encrypted vaults inside your application (sealed-box, libsodium, etc.)

## Storage patterns that are NOT OK

- Vault files in this framework (the `vault/` tree is readable by anyone with repo access)
- Commit messages or commit bodies
- README / documentation files
- Slack messages, email, any chat history
- Code comments
- Log files that get shipped to a logging service

---

## If a credential slips into a repo

1. **Rotate the credential first.** Revocation is more urgent than git cleanup.
2. Remove from git history using `git filter-repo` or BFG, then force-push.
3. Treat the old value as compromised — assume it was scraped.
4. Add a decision log entry explaining the rotation so future Claude sessions know not to reuse.

---

## Claude Code specific

- `~/.claude/.credentials.json` holds OAuth tokens for the Claude API. **Never track this in git.** Zaude's `.gitignore` excludes it; verify on every `git status` before pushing the config repo.
- `~/.zaude/config.json` does NOT hold credentials — only paths and project names. Safe to version-control.
- Hooks run under your user account and can read the environment. Never set a credential as a global env var that hooks could accidentally log.
