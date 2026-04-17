# Customizing Zaude for your workflow

Zaude ships opinionated defaults, but almost every part is replaceable. This doc walks through what's customizable, with five concrete examples, and explains when to fork the upstream repo versus keeping changes local.

Before customizing, read [11-best-practices.md](./11-best-practices.md) — it explains *why* the defaults are shaped the way they are. Undoing a default without understanding the rationale is how projects end up with unmaintainable one-offs.

---

## What's customizable

Every layer of Zaude is editable. Higher in the table = more likely to customize, lower = customize with care.

| Layer | Where | Typical edits |
|---|---|---|
| Project vault files | `<vault>/01-projects/<project>/` | Always — this is your work |
| Zaude config | `~/.zaude/config.json` | Frozen zones, cwd mappings, session-log depth |
| Cross-project patterns | `<vault>/03-patterns/*.md` | Add your team rules |
| Slash commands | `~/.claude/commands/*.md` | Add new commands, tweak existing ones |
| Global instructions | `~/.claude/CLAUDE.md` | Your voice / conventions |
| Hooks | `~/.claude/hooks/*` | Add new hooks, modify existing logic |
| Custom agents | `~/.claude/agents/*.md` | Add domain-specific reviewers |
| `settings.json` | `~/.claude/settings.json` | Register new hooks, adjust matchers |

---

## `~/.zaude/config.json` — fields explained

The config file Zaude's hooks read. Lives at `~/.zaude/config.json`. Safe to version-control (no credentials).

```json
{
  "vault_path": "~/zaude-vault",
  "projects_subdir": "01-projects",
  "patterns_subdir": "03-patterns",
  "cwd_to_project": {
    "my-repo-basename": "vault-folder-slug"
  },
  "frozen_zones": [
    "src/vendor/",
    "legacy-app/"
  ],
  "recent_session_logs": 3,
  "claude_config_path": "~/.claude"
}
```

### `vault_path`

Absolute or `~`-prefixed path to your vault root. The SessionStart hook fails open (no context) if this doesn't resolve — it never errors, so check manually if you move the vault.

### `projects_subdir`

Directory under `vault_path` that holds per-project folders. Default `01-projects`. Rename only if you want a different top-level layout.

### `patterns_subdir`

Directory under `vault_path` that holds cross-project rule files. Default `03-patterns`. Every `.md` here is loaded into context on session start. Add files freely; the hook picks them up automatically.

### `cwd_to_project`

Map from cwd basename to vault project slug. Used when your working directory name doesn't match your vault folder name. The hook walks up from cwd looking for matches; this map gives explicit overrides.

Common use: monorepo with `packages/web/`, `packages/api/`, etc., where you want all sub-packages to share one vault project:

```json
{
  "cwd_to_project": {
    "web": "my-app",
    "api": "my-app",
    "shared": "my-app"
  }
}
```

### `frozen_zones`

List of path substrings that `PreToolUse` frozen-guard hook blocks for Edit/Write. Substring match, not glob — `src/vendor` matches any path containing that string.

Leave `[]` to disable the guard entirely.

### `recent_session_logs`

How many recent session log files the SessionStart hook loads into context. Default 3. Higher values = more history carried forward but larger context window cost.

Rule of thumb:
- Short sessions (< 1h), rare: 3 is plenty.
- Long sessions (2–4h), frequent: 5–7 captures the last work-week.
- Rapid iteration on one feature: 7–10 keeps the whole arc visible.

Changing this:

```json
{
  "recent_session_logs": 7
}
```

### `claude_config_path`

Where `~/.claude` lives. The hook uses this to locate the memory directory (`<claude_config_path>/projects/<encoded-cwd>/memory/`). Almost always `~/.claude`.

---

## Example 1 — Adding a pattern file for AWS deployments

Scenario: your team always deploys to AWS using Terraform. You want every session to start with those rules in context.

Create a new pattern file:

```bash
nvim ~/zaude-vault/03-patterns/aws-deployment.md
```

Content:

```markdown
# AWS Deployment Patterns

Cross-project rules for any service deployed to AWS.

---

## Rule 1 — Terraform state lives in S3 + DynamoDB

All Terraform state uses a remote backend:

- S3 bucket: `{company}-tf-state-{env}`
- DynamoDB table: `terraform-locks` (per account, not per project)
- Encryption: SSE-S3, versioning enabled

Never commit `.tfstate`. Never run Terraform without the backend configured.

---

## Rule 2 — Secrets come from SSM Parameter Store

No hardcoded credentials in Terraform. No env vars set in task definitions
from `.tfvars`. Every secret reads from `/app/{project}/{env}/{name}` in SSM.

Rationale: rotation changes the SSM value, tasks restart, no redeploy.

---

## Rule 3 — IAM role scopes

Task roles are scoped per-service. No shared `AppRole`. New service = new role.

...
```

Save and commit. The next session's SessionStart hook will pick it up automatically — `03-patterns/*.md` is loaded wholesale, no registration needed.

Verify by opening a new session and typing `/start`. Claude should mention the AWS rules are in context if you ask, and will apply them automatically during `/build`.

---

## Example 2 — Adding a `/test` slash command

Scenario: before `/ship`, you always run the full test suite. You want a dedicated `/test` command so you (and Claude) have one canonical way to do it.

Create the command:

```bash
nvim ~/.claude/commands/test.md
```

Content:

```markdown
Run the full test suite and report pass/fail summary.

## Steps

1. Detect the package manager:
   - `package.json` present → use `npm`, `yarn`, `pnpm`, or `bun` per lockfile
   - `pyproject.toml` → use `uv`, `poetry`, or `pytest` directly
   - `Cargo.toml` → `cargo test`
   - `go.mod` → `go test ./...`
2. Run the test command.
3. Report:
   - Total tests, passed, failed
   - For each failure: test name, first 5 lines of the error
   - Total duration
4. Do NOT fix failures. Do NOT modify any files. Report only.

## Output format

If all pass:
```
✓ 247 tests passed in 12.3s
```

If failures:
```
✗ 3 of 247 tests failed in 12.3s

FAIL packages/api/src/routes/auth.test.ts > "reset-request rate limit"
  Expected: 429
  Received: 200
  at line 78

FAIL ...
```

## When to run

- Before `/ship` — if tests fail, fix before shipping
- During `/build` — after implementation, before the review chain
- On demand — any time you want to check current state
```

Save. The file is now a slash command. Open a new session; type `/test` — Claude reads the markdown and follows the instructions.

**Integrating with `/build`.** If you want `/build` to run tests automatically before the review chain, edit `~/.claude/commands/build.md` to insert a step:

```markdown
3b. **Run the test suite** — invoke `/test` equivalent (run the full test suite).
    If any test fails, STOP and report. Do not proceed to review chain.
```

Claude reads the updated build.md next session.

---

## Example 3 — Custom frozen-guard zone for `vendor/`

Scenario: your project has a `vendor/` directory with checked-in third-party code. Claude should never edit it.

Edit `~/.zaude/config.json`:

```json
{
  "vault_path": "~/zaude-vault",
  "cwd_to_project": {},
  "frozen_zones": [
    "/vendor/"
  ],
  "recent_session_logs": 3,
  "claude_config_path": "~/.claude"
}
```

The leading slash disambiguates `vendor/` as a directory — `src/vendor/lib.ts` matches, but `my-vendors-list.md` does not.

Test it. In a session, ask Claude to edit a file under `vendor/`. The `PreToolUse` hook fires and denies:

```
BLOCKED: /your/repo/vendor/lib.ts is inside the frozen zone '/vendor/'.
This path is read-only by Zaude configuration (~/.zaude/config.json).
```

Claude reports the block, you decide whether to override.

**Tip:** `frozen_zones` is substring-matched, not glob-matched. If you want project-specific zones:

```json
{
  "frozen_zones": [
    "repo-a/legacy/",
    "repo-b/vendor/"
  ]
}
```

Each substring applies across all repos. If substring logic isn't expressive enough, see [Example 4](#example-4--writing-a-new-hook) for writing a custom hook.

---

## Example 4 — Writing a new hook (auto-format on write)

Scenario: you want every `.ts` / `.tsx` file Claude writes to be auto-formatted with Prettier before the write commits.

### Step 1 — Write the hook

Create `~/.claude/hooks/format-on-write.py`:

```python
#!/usr/bin/env python3
"""PreToolUse hook — run prettier on TS/TSX files before write."""
import json
import os
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""

    if not file_path:
        return 0

    # Only format TS/TSX
    if not (file_path.endswith(".ts") or file_path.endswith(".tsx")):
        return 0

    # Only format on Write, not Edit (Edit has specific old/new strings)
    if data.get("tool_name") != "Write":
        return 0

    content = tool_input.get("content") or ""
    if not content:
        return 0

    # Run prettier on stdin
    try:
        result = subprocess.run(
            ["npx", "prettier", "--parser", "typescript"],
            input=content,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # prettier failed — let the original write through
            return 0
        formatted = result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0

    if formatted == content:
        return 0  # already formatted, nothing to do

    # Modify the tool input to use the formatted content
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "toolInput": {
                **tool_input,
                "content": formatted,
            },
        }
    }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```bash
chmod +x ~/.claude/hooks/format-on-write.py
```

### Step 2 — Register in settings.json

Edit `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/frozen-guard.py\"",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/format-on-write.py\"",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

Two separate `PreToolUse` entries, each with its own matcher. The frozen-guard runs on Edit+Write; the formatter only on Write. Order within each entry matters — the harness runs them in sequence.

### Step 3 — Test

Restart Claude Code (hooks are loaded at session start). Ask Claude to write a TS file. The formatter runs, the file lands pre-formatted.

**Important caveats:**
- Formatting before write means `code-reviewer` sees the formatted version. If reviewer complains about style, it's your Prettier config, not Claude.
- If Prettier fails (missing node_modules, bad config), the hook exits 0 and the original write goes through. Fail-open is deliberate — a broken formatter should not block your work.
- `timeout: 15` gives Prettier enough time. Bump higher for big files.

---

## Example 5 — Adjusting `recent_session_logs`

Scenario: you're in the middle of a multi-week feature with daily sessions. You want the last 7 days of logs in context automatically, not 3.

Edit `~/.zaude/config.json`:

```json
{
  "vault_path": "~/zaude-vault",
  "cwd_to_project": {},
  "frozen_zones": [],
  "recent_session_logs": 7,
  "claude_config_path": "~/.claude"
}
```

Save. Next session, the hook reads 7 most recent session logs instead of 3.

**When to bump up:**
- Multi-day features with lots of small ships — 7 carries the full arc
- Slow projects where sessions are weeks apart — 7 grabs more context
- When you catch yourself explaining context Claude should already have

**When to keep it at 3:**
- Default case. Enough context, small footprint.
- Finished features — no reason to reload month-old logs.

You can also bump temporarily for one session by editing the config mid-session. The hook only runs at session start, so bump it, open a fresh session, close when done, drop it back.

---

## Adding a custom agent

Agents live in `~/.claude/agents/<name>.md`. They're Markdown files describing a specialized Claude task. Zaude's `/build` references `code-reviewer`, `security-auditor`, `architect-review`, `workflow-orchestrator`, `design-bridge`, `backend-developer`, `frontend-developer`. You can add more.

Example — a `postgres-reviewer` for projects heavy on SQL migrations:

```bash
nvim ~/.claude/agents/postgres-reviewer.md
```

```markdown
# Postgres Reviewer

Review Postgres-specific changes for correctness and performance.

## When to invoke

Any diff that touches:
- `.sql` files
- Migration files (e.g. `migrations/*.ts`, `db/migrate/*.rb`)
- Raw SQL in application code

## What to check

1. **Migrations are forward-safe.** `ALTER TABLE ADD COLUMN NOT NULL`
   on a large table requires a default value; a rollback needs to
   drop it cleanly.
2. **Indexes match query patterns.** New queries hit new indexes.
3. **Constraints are named.** `CONSTRAINT fk_user_workspace` beats
   auto-generated names.
4. **No `SELECT *` in production code.** Specific columns only.
5. **N+1 queries.** If the code is in a loop, check for batch fetch.

## Output format

Severity-tagged findings with file:line references. Same format as
`code-reviewer`.
```

After save, reference the agent in `/build` or `/review` (edit those commands to include an `invoke postgres-reviewer on any SQL diff` step).

---

## Editing global `CLAUDE.md`

`~/.claude/CLAUDE.md` sets behavioral defaults across every project. The Zaude template at [`templates/claude-config/CLAUDE.md`](../templates/claude-config/CLAUDE.md) is a starting point; edit freely.

Common customizations:

### Changing the slash command table

If you added a `/test` command, add a row to the table at the top:

```markdown
| **`/test`** | Run full test suite, report pass/fail | Before /ship |
```

### Tightening or loosening the announcement list

The default list of actions requiring loud announcement is conservative. If your workflow touches databases daily and the announcement is noise, remove "Running migrations against production" — but understand you're trading safety for speed.

### Adding your voice

If you prefer Claude to ask before proposing alternatives, add a section:

```markdown
## Personal preferences

- When you propose an alternative to my approach, present it as a
  numbered list with tradeoffs — don't just pick one.
- Be more verbose on architectural decisions, less on implementation.
- When I paste a log, wait for me to ask before interpreting it.
```

These become part of every session's context. Edits take effect on the next session.

### What not to remove

- The permission-mode announcement pattern if you use `--dangerously-skip-permissions`. Removing it removes your only safety net.
- The credential-handling section. Never useful to drop.
- The "no mock data" rule. Removing it invites silent test-only bugs into production.

---

## When to fork Zaude vs customize locally

Local customization:

- Your frozen zones are specific to your repos
- Your global CLAUDE.md is tuned to your voice
- You added a `/test` command that runs *your* test suite
- Your vault has company-internal patterns

→ **Keep it local.** Copy files into `~/.claude/` and `~/.zaude/`, git-track your claude-config repo, done.

Fork Zaude (or open a PR upstream):

- Your changes are generally useful (a pattern file for "Django + Postgres projects", a better hook that most people would benefit from)
- You found a bug in a template or hook
- You have a new slash command that fits the canonical five
- You wrote better docs

→ **Fork on GitHub, make changes, open a PR.** Either it gets merged (best outcome) or your fork lives as a spec that others can cherry-pick from. Either way, the framework improves.

### Forking mechanics

```bash
# fork on github.com/ziadmomen10/zaude → github.com/you/zaude
git clone git@github.com:you/zaude.git
cd zaude
# make changes
git commit -m "feat: add postgres-reviewer agent template"
git push
# open PR from github UI
```

Point your installer at your fork:

```bash
curl -fsSL https://raw.githubusercontent.com/you/zaude/main/install/install.sh | bash
```

On new machines, this installs your custom version. If upstream catches up, rebase your fork.

---

## Safe vs dangerous customizations

### Safe — minimal risk

- Adding files to `03-patterns/`
- Adding new slash commands
- Adding `cwd_to_project` entries
- Tweaking `recent_session_logs`
- Adding new agents
- Editing global `CLAUDE.md` tone

### Moderate — test before relying on

- Adding new hooks (they fire on every tool call — bugs slow you down)
- Changing `frozen_zones` (removing a zone opens up writes that were blocked)
- Modifying existing slash commands (you might lose the review chain)

### Dangerous — know what you're undoing

- Deleting `PreToolUse` frozen-guard (removes all path protection)
- Deleting `SessionEnd` sync (vault drift within days)
- Removing review agents from `/build` / `/ship` skills (review chain bypassed)
- Setting `recent_session_logs: 0` (no history loaded)

Rule of thumb: if the default is a hook, think twice before removing. Hooks exist because a past failure mode made them necessary.

---

## Testing customizations

Every customization should be verified before you rely on it.

| Changed | How to verify |
|---|---|
| `~/.zaude/config.json` | Run the hook manually: `echo '{"cwd":"'"$PWD"'"}' \| python ~/.claude/hooks/session-start-vault.py` |
| Pattern file | Open new session, `/start`, ask Claude to confirm the pattern loaded |
| New slash command | Open new session, type the command, check behavior matches skill text |
| New hook | Open new session, trigger the hook's event (write a file, end session), check the hook ran |
| Global CLAUDE.md edits | Open new session, test the changed behavior |

If verification fails, roll back. Customizations that sound good in theory often have subtle interactions you won't catch without a real session.

---

## Sharing customizations with your team

If your team all uses Zaude, you probably want shared patterns and commands. Two approaches:

### Approach A — team fork

Fork Zaude to a team repo, apply team-specific changes, point everyone's installer at the team fork. Upstream updates flow down via rebase.

### Approach B — custom bootstrap repo

Keep Zaude upstream unchanged. Make a separate team repo (`company-zaude-extras`) with:

- Pattern files to copy into `03-patterns/`
- Slash commands to copy into `~/.claude/commands/`
- A bootstrap script that runs after Zaude install and layers team extras on top

Approach B keeps Zaude updates frictionless and team customizations modular. Approach A is simpler when changes are invasive.

---

## Reverting a customization you regret

Everything Zaude installs is reversible:

```bash
# revert config
cp ~/.zaude/config.json ~/.zaude/config.json.bak
curl -fsSL https://raw.githubusercontent.com/ziadmomen10/zaude/main/templates/claude-config/config.sample.json > ~/.zaude/config.json

# revert a specific hook
curl -fsSL https://raw.githubusercontent.com/ziadmomen10/zaude/main/templates/claude-config/hooks/session-start-vault.py > ~/.claude/hooks/session-start-vault.py

# revert settings.json
cp ~/.claude/settings.json ~/.claude/settings.json.bak
curl -fsSL https://raw.githubusercontent.com/ziadmomen10/zaude/main/templates/claude-config/settings.json > ~/.claude/settings.json
```

If you git-track `~/.claude`, `git checkout` is faster:

```bash
cd ~/.claude
git checkout HEAD -- hooks/session-start-vault.py
git checkout HEAD -- settings.json
```

That's the strongest argument for keeping `~/.claude` in git — it's the undo button for every customization.

---

## See also

- [06-hooks.md](./06-hooks.md) — the internals of each hook, for reference when writing new ones
- [05-commands.md](./05-commands.md) — the slash command contract
- [11-best-practices.md](./11-best-practices.md) — the philosophy (customize defaults carefully)
- [12-troubleshooting.md](./12-troubleshooting.md) — when a customization breaks something

## What's next

Pick one customization from this doc that matches your workflow and do it this week. Don't customize everything at once — each change is a chance to break something. Ship one, test it for a few sessions, then consider the next.
