# 02 — Installation

This doc walks you through installing Zaude on macOS, Linux, WSL, and Windows. There are three install paths; pick one.

Total install time: **5-10 minutes**.

---

## Prerequisites

| Tool | Required | Why | Check |
|---|---|---|---|
| [Claude Code](https://claude.com/claude-code) | Yes | Zaude hooks run inside Claude Code | `claude --version` |
| `git` | Yes | Vault and config are git repos | `git --version` |
| Python 3 | Yes | Two hooks are Python scripts | `python3 --version` (or `python --version` on Windows) |
| `bash` | Yes (non-Windows) | `SessionEnd` hook is a bash script | `bash --version` |
| [`gh` CLI](https://cli.github.com) | Recommended | Auto-creates your private GitHub repos | `gh --version` + `gh auth status` |
| A GitHub account | Recommended | Vault and config push to private repos | — |

If `gh` is missing, Zaude still installs; you just have to create the GitHub repos manually afterwards.

**Windows note:** Zaude's `SessionEnd` hook is a bash script. On native Windows (not WSL) it won't run unless you have Git Bash or similar. The `install.ps1` installer ships a PowerShell equivalent; use it instead of `install.sh`.

---

## Pick an install path

Three options, same result. Pick whichever feels best.

| Path | Best for | What it does |
|---|---|---|
| **A — Paste the setup prompt** | First-time users who want to see each step | Claude walks you through the install interactively, asking questions and showing diffs before every overwrite |
| **B — `install.sh`** | macOS / Linux / WSL users who want a one-liner | Non-interactive bash installer; prompts for a handful of inputs and does the rest |
| **C — `install.ps1`** | Native Windows PowerShell users | Same as B, in PowerShell |

---

## Path A — Paste the setup prompt (recommended for first-timers)

This is the most transparent install. You paste a prompt into a new Claude Code session, and Claude walks through each step with you, asking for confirmation before anything destructive.

### Step 1 — Open a new Claude Code session

Open Claude Code in any directory. The working directory doesn't matter for the install itself.

### Step 2 — Paste the setup prompt

Open [`install/setup-prompt.md`](../install/setup-prompt.md) and copy the block between the `⬇` and `⬆` markers. Paste the entire block into your Claude Code chat and press enter.

Claude will start at Step 1 of the prompt, which asks:

```
1. Where should the vault live? (Default: ~/zaude-vault)
2. What GitHub username will own the private vault and config repos?
3. Should frozen-guard be enabled? If yes, what path substrings?
4. Do I already have files in ~/.claude/commands/ or ~/.claude/hooks/ that might conflict?
```

Answer each. Claude will show you the command it's about to run before running it — approve each one.

### Step 3 — Verify the hook fires

When the install finishes, Claude will tell you to **close this session and open a new one in your project directory**. In the new session, the initial system reminder should contain a block that starts with:

```
=== VAULT CONTEXT FOR <your-project-slug> ===
```

If you see that block, you're done. Run `/start` to confirm.

---

## Path B — `install.sh` (macOS / Linux / WSL)

One-line install:

```bash
curl -fsSL https://raw.githubusercontent.com/ziadmomen10/zaude/main/install/install.sh | bash
```

### Step 1 — The installer asks four questions

```
Where should your vault live? [/home/you/zaude-vault]:
GitHub username for private repos [your-gh-user]:
First project slug (lowercase-with-dashes) [my-first-project]:
Current working directory for that project (absolute path) [/home/you/my-first-project]:
Frozen path substrings (comma-separated, or blank for none) []:
```

Defaults are sensible; press enter to accept them or type a custom value.

### Step 2 — The installer clones Zaude and installs

Expected output:

```
▸ Checking prerequisites...
✓ Prerequisites OK.
▸ Cloning Zaude into /tmp/tmp.XXXX...
✓ Cloned.
▸ Creating vault at /home/you/zaude-vault...
✓ Vault scaffolded. First project: my-app
▸ Installing hooks into /home/you/.claude/hooks...
✓ Hooks installed.
▸ Installing commands into /home/you/.claude/commands...
✓ Commands installed.
✓ settings.json created.
✓ Global CLAUDE.md created.
✓ Wrote /home/you/.zaude/config.json
```

### Step 3 — The installer creates your GitHub repos

If `gh` is installed and authenticated, you'll see:

```
Create private GitHub repos for vault + claude-config? [y/N]: y
▸ Creating github.com/your-user/zaude-vault (private)...
▸ Creating github.com/your-user/zaude-claude-config (private)...
▸ Initializing vault git repo...
✓ Vault pushed.
▸ Initializing ~/.claude git repo with curated .gitignore...
✓ Claude-config pushed.
```

### Step 4 — Confirmation

```
Zaude installed.

  Vault:         /home/you/zaude-vault
  Claude config: /home/you/.claude
  Config file:   /home/you/.zaude/config.json
  First project: my-app (mapped to cwd basename "my-app")

Next:
  1. Open a new Claude Code session in /home/you/my-app
  2. The initial system reminder should include "=== VAULT CONTEXT FOR my-app ==="
  3. Run /start to confirm Zaude is loaded
  4. Start shipping
```

---

## Path C — `install.ps1` (native Windows PowerShell)

One-line install:

```powershell
irm https://raw.githubusercontent.com/ziadmomen10/zaude/main/install/install.ps1 | iex
```

The PowerShell installer follows the same flow as `install.sh`. It installs a `.ps1` SessionEnd sync script instead of the bash one so you don't need Git Bash.

If you're on Windows but prefer WSL, use Path B from inside WSL — that path will install into your WSL home directory, not your Windows one.

---

## Post-install verification

Run these three checks regardless of which path you used.

### Check 1 — Config file exists

```bash
cat ~/.zaude/config.json
```

Expected output (paths reflect your install):

```json
{
  "vault_path": "/home/you/zaude-vault",
  "projects_subdir": "01-projects",
  "patterns_subdir": "03-patterns",
  "cwd_to_project": {
    "my-app": "my-app"
  },
  "frozen_zones": [],
  "recent_session_logs": 3,
  "claude_config_path": "/home/you/.claude"
}
```

### Check 2 — Hooks are executable

```bash
ls -l ~/.claude/hooks/
```

Expected: `session-start-vault.py`, `frozen-guard.py`, and `session-end-vault-sync.sh` (or `.ps1` on Windows), all with `x` permission bits.

### Check 3 — SessionStart hook fires

Open a **new** Claude Code session in the directory you mapped to a vault project. The first system reminder should contain:

```
=== VAULT CONTEXT FOR <your-slug> ===

## CLAUDE.md
<your project's CLAUDE.md content>

## current-state.md
<your project's current-state.md content>
...
```

Run `/start`. You should see a "Last session summary / In-flight work / Blockers / Next action" report.

If the context block doesn't appear, jump to [Troubleshooting](#troubleshooting) below.

---

## Troubleshooting

### `python3: command not found`

The SessionStart and frozen-guard hooks are Python 3 scripts. They need `python3` on PATH.

**macOS:** `brew install python3`
**Linux (Debian/Ubuntu):** `sudo apt install python3`
**Windows:** [python.org installer](https://www.python.org/downloads/) — check "Add Python to PATH" during install. If your system calls it `python` not `python3`, edit the hook entries in `~/.claude/settings.json` to use `python` instead.

### `gh: command not found` or `gh auth status` fails

`gh` is optional but recommended. Without it the installer skips GitHub repo creation; you'll need to create `zaude-vault` and `zaude-claude-config` repos manually and push.

**Install:** [cli.github.com](https://cli.github.com)
**Authenticate:** `gh auth login` (pick HTTPS + web-based auth, easiest path)

After `gh` is set up, re-run the installer — the repos + push steps will complete.

### `~/.claude/settings.json already exists`

Zaude won't overwrite your existing `settings.json`. You need to merge the hook entries manually. Open `~/zaude/templates/claude-config/settings.json` (or the cloned copy) and copy the `hooks` block into your existing file. The relevant entries look like:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/session-start-vault.py" }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/frozen-guard.py" }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "bash ~/.claude/hooks/session-end-vault-sync.sh" }
        ]
      }
    ]
  }
}
```

Merge those into your existing `hooks` object (don't replace other hooks you already had).

### `=== VAULT CONTEXT FOR ... ===` doesn't appear in new sessions

Three likely causes.

**(a) The cwd doesn't map to a vault project.** Open `~/.zaude/config.json`, look at `cwd_to_project`. The key must match the basename of the directory you opened Claude Code in. Example: if your cwd is `/home/you/my-app`, the key must be `my-app`.

```bash
# Add a mapping manually
python3 -c "
import json
p = '$HOME/.zaude/config.json'
c = json.load(open(p))
c['cwd_to_project']['my-app'] = 'my-app'
json.dump(c, open(p, 'w'), indent=2)
"
```

**(b) The vault project folder doesn't exist.** Check `ls ~/zaude-vault/01-projects/`. The folder name must match the value (not the key) in `cwd_to_project`.

**(c) The hook isn't configured in settings.json.** Run:

```bash
cat ~/.claude/settings.json | python3 -m json.tool
```

Confirm there's a `hooks.SessionStart` entry pointing at `session-start-vault.py`. If missing, see the "settings.json already exists" section above.

### Permission denied running the hook

```bash
chmod +x ~/.claude/hooks/session-start-vault.py
chmod +x ~/.claude/hooks/frozen-guard.py
chmod +x ~/.claude/hooks/session-end-vault-sync.sh
```

On Windows, ensure the scripts have a correct shebang and that PowerShell's execution policy allows running them. For `.ps1` alternatives, you may need:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Hook exits silently and no context appears

The hook is designed to never block session start — if anything fails, it silently prints `{}` and the session opens normally. To debug, run the hook manually:

```bash
echo '{"cwd":"/full/path/to/your/project"}' | python3 ~/.claude/hooks/session-start-vault.py
```

Expected: a JSON object with a `hookSpecificOutput.additionalContext` field containing the vault content.

If you get `{}` back, one of:
- `vault_path` in `~/.zaude/config.json` doesn't exist or is wrong
- `cwd_to_project` doesn't have an entry matching your cwd basename
- The vault project folder under `01-projects/` is missing

### `git push` fails for the vault or config repo

Two common causes.

**(a) No remote set.** Run `git -C ~/zaude-vault remote -v`. If empty, add one:

```bash
git -C ~/zaude-vault remote add origin https://github.com/<you>/zaude-vault.git
git -C ~/zaude-vault push -u origin main
```

**(b) Remote has commits you don't have locally.** Never force-push the vault. Instead:

```bash
git -C ~/zaude-vault fetch origin
git -C ~/zaude-vault pull --rebase origin main
git -C ~/zaude-vault push
```

### The `SessionEnd` hook logged an error

Check the log:

```bash
cat ~/.claude/hooks/session-end-vault-sync.log
```

Common errors and fixes:

| Log message | Fix |
|---|---|
| `path not set or directory not found` | Edit `~/.zaude/config.json` to fix `vault_path` / `claude_config_path` |
| `not a git repo, skipping` | Run `git init -b main` inside that directory, add a remote, push once manually |
| `commit failed, leaving staged` | A pre-commit hook in that repo rejected the auto-commit. Run the commit manually and fix whatever the hook flagged |
| `push failed, commit kept locally` | Usually means remote has newer commits. Run `git pull --rebase` then push |

The `SessionEnd` hook **never** fails session exit — errors are logged and swallowed. Your session always closes cleanly.

---

## Uninstall

Zaude is a collection of files. Uninstall is `rm`-based.

### Remove Zaude's config

```bash
rm -rf ~/.zaude/
```

### Remove Zaude's files from `~/.claude/`

```bash
rm ~/.claude/hooks/session-start-vault.py
rm ~/.claude/hooks/frozen-guard.py
rm ~/.claude/hooks/session-end-vault-sync.sh
rm ~/.claude/commands/start.md
rm ~/.claude/commands/build.md
rm ~/.claude/commands/review.md
rm ~/.claude/commands/ship.md
rm ~/.claude/commands/wrap.md
```

Then open `~/.claude/settings.json` and remove the three hook entries (SessionStart, PreToolUse, SessionEnd) that reference the scripts above.

If you appended Zaude to an existing `~/.claude/CLAUDE.md`, open it and delete the section between the `<!-- Zaude framework -->` marker and the next `---`.

### Remove your vault (optional)

```bash
rm -rf ~/zaude-vault
```

Your GitHub vault repo stays — delete it from the GitHub UI if you want.

### Verify clean

Open a new Claude Code session. You should **not** see the `=== VAULT CONTEXT ===` block anymore, and `/start`, `/build`, `/review`, `/ship`, `/wrap` should all report "command not found".

---

## Updating Zaude

To pull in upstream changes to hooks, commands, or templates:

```bash
# Re-run the installer against the same paths — it'll ask before overwriting each file
curl -fsSL https://raw.githubusercontent.com/ziadmomen10/zaude/main/install/install.sh | bash
```

Or clone the repo and copy the specific files you want:

```bash
git clone --depth 1 https://github.com/ziadmomen10/zaude /tmp/zaude-upgrade
cp /tmp/zaude-upgrade/templates/claude-config/hooks/session-start-vault.py ~/.claude/hooks/
# ...etc
```

Your vault content is untouched by upgrades — the installer only touches `~/.claude/`, `~/.zaude/`, and the vault template folder if the project doesn't exist yet.

---

## What's next

| Topic | Go to |
|---|---|
| Understand the system you just installed | [03 — Architecture](./03-architecture.md) |
| Learn the vault layout | [04 — Vault pattern](./04-vault.md) |
| Use the five slash commands | [05 — Commands](./05-commands.md) |

See also: the [setup prompt](../install/setup-prompt.md), the [install.sh source](../install/install.sh), and [`config.sample.json`](../templates/claude-config/config.sample.json) for the config schema.
