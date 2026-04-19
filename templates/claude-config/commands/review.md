Run the full review chain on the current uncommitted changes in this repo. Do NOT fix anything — just report.

## Steps

1. Run `git diff` and `git status` to capture what's changed.
2. Determine which reviewers apply:
   - `code-reviewer` — always, on any diff
   - `architect-review` in REVIEW mode — always, on any structural change (new service, new route, new middleware, schema change, new major component)
   - `security-auditor` — only if the diff touches auth, JWT, passwords, encryption, credential storage, SSH operations, or input validation
3. Invoke each applicable reviewer in order with the diff as context.
4. Collect findings from each reviewer.

## Report format

Organize findings by severity, with each finding containing:
- **Severity** (CRITICAL / HIGH / MEDIUM / LOW)
- **Reviewer** (which agent raised it)
- **File:line** (exact location)
- **Issue** (one-sentence description)
- **Recommendation** (what to do — not the fix code)

Example:
```
## CRITICAL
### [security-auditor] packages/backend/src/routes/auth.ts:87
Unparameterized SQL query permits injection via `email` field.
→ Rewrite with drizzle query builder or parameterized string template.
```

If NO findings, say so plainly: "Clean. N files reviewed, 0 findings."

Do NOT commit anything. Do NOT modify any files. This command is read-only.

## Agent dispatch — single source of truth

For the full dispatch matrix (including v0.5 VoltAgent specialists), read `03-patterns/agent-usage.md`. Review chains invoke the `-readonly` variants of write-capable agents to preserve this command's read-only contract. Never duplicate dispatch rules inline in this file.
