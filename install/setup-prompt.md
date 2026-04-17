# Zaude Setup Prompt

Paste the entire block below into a **new Claude Code session** (any working directory). Claude will walk you through installation interactively.

**Prerequisites:**
- [Claude Code](https://claude.com/claude-code) installed and running
- `git` available on PATH
- Python 3 available on PATH
- `gh` CLI installed and authenticated (`gh auth login`)
- A GitHub account

---

## Copy everything from here ⬇

```
I want to install the Zaude framework from https://github.com/ziadmomen10/zaude.

Zaude is a Claude Code framework that provides:
- Persistent memory across sessions via a SessionStart hook
- A structured vault pattern (CLAUDE.md, current-state.md, decisions.md, open-questions.md, sessions/)
- Five slash commands (/start, /build, /review, /ship, /wrap)
- Credential hygiene and frozen-zone protection
- Automatic git sync for both vault and config

Please walk me through installation step by step. At each step, ask me any questions you need, then show me the command you're about to run BEFORE running it. Proceed only after I confirm.

# Step 1 — Gather info
Ask me:
1. Where should the vault live? (Default: ~/zaude-vault)
2. What GitHub username will own the private vault and config repos? (e.g. my-github-user)
3. Should frozen-guard be enabled? If yes, what path substrings should be frozen? (Default: none)
4. Do I already have files in ~/.claude/commands/ or ~/.claude/hooks/ that might conflict?

# Step 2 — Clone Zaude templates
Clone https://github.com/ziadmomen10/zaude into a temporary directory (e.g. /tmp/zaude or $HOME/zaude-install). Do not touch anywhere else yet.

# Step 3 — Create the vault
Create the vault directory I chose, copy everything from templates/vault/ into it (including VAULT_PROTOCOL.md, 03-patterns/, and the _template project folder renamed to a project slug I'll provide).

# Step 4 — Install Claude Code config
Copy templates/claude-config/commands/*.md into ~/.claude/commands/ — but if files already exist with the same name, show me the diff and ASK before overwriting.
Copy templates/claude-config/hooks/*.py and *.sh into ~/.claude/hooks/ — same: diff + ask if conflicts.
Make the hooks executable: chmod +x ~/.claude/hooks/*.py ~/.claude/hooks/*.sh
Merge templates/claude-config/settings.json into ~/.claude/settings.json. If I have existing hooks, show me the merged result before writing.
Copy templates/claude-config/CLAUDE.md to ~/.claude/CLAUDE.md — if I already have a ~/.claude/CLAUDE.md, APPEND Zaude's content to mine with a clear separator; do not overwrite.

# Step 5 — Write the Zaude config
Create ~/.zaude/config.json based on templates/claude-config/config.sample.json, filling in:
- vault_path: the path I chose in step 1
- projects_subdir: "01-projects"
- patterns_subdir: "03-patterns"
- claude_config_path: ~/.claude (expanded)
- cwd_to_project: {} for now (we'll add entries as I onboard projects)
- frozen_zones: whatever I gave you in step 1
- recent_session_logs: 3

# Step 6 — Scaffold my first project
Ask me:
- What's the project slug? (e.g. my-app)
- What's the project name?
- One-sentence description?
- Main stack (React, Rails, Go, etc.)?
- The current working directory where I'll be editing this project?

Rename the vault's _template folder to my slug and fill in CLAUDE.md, current-state.md (just the skeleton), spec.md with my answers.
Then add an entry to ~/.zaude/config.json cwd_to_project mapping my cwd's basename → my slug.

# Step 7 — Create two private GitHub repos
Using gh CLI:
- gh repo create <username>/zaude-vault --private --description "My Zaude vault"
- gh repo create <username>/zaude-claude-config --private --description "My Zaude Claude-Code config"
Show me the commands before running.

# Step 8 — Initialize both repos locally
For the vault:
- cd to vault_path
- git init -b main
- Add a README.md with a short description ("My Zaude vault — project knowledge, decisions, session logs")
- git add -A && git commit + push

For the Claude config:
- cd ~/.claude
- git init -b main (skip if already a repo)
- Write a curated .gitignore that excludes everything except: commands/, hooks/, agents/, skills/, CLAUDE.md, settings.json, projects/*/memory/, README.md
- Add a short README.md
- git add + commit + push
- IMPORTANT: before committing, run `git status` and show me. Verify no .credentials.json or similar secrets will be tracked. STOP if anything looks wrong.

# Step 9 — Verify the hook fires
Tell me to close this Claude Code session and open a new one in the cwd I mapped to my first project. The new session should see a `=== VAULT CONTEXT FOR <slug> ===` section in its initial system reminder. If it doesn't, something's wrong and we debug.

# Step 10 — Summary
Report:
- Where the vault is
- Where the Claude config is
- Both GitHub repo URLs
- What to do first in the new session: /start, then pick real work

GATES:
- Never push anything that would expose credentials
- Never force-push
- Never skip the "show me the diff before overwriting" step — I want to see exactly what's going into ~/.claude/
- Never run destructive operations without announcing them

Start with Step 1. Wait for my answers before moving to Step 2.
```

## ⬆ Copy everything above

After pasting, Claude will ask you the setup questions and walk through each step. Expect the full install to take ~5–10 minutes.

---

## If you'd rather run a script

```bash
# macOS / Linux / WSL
curl -fsSL https://raw.githubusercontent.com/ziadmomen10/zaude/main/install/install.sh | bash
```

```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/ziadmomen10/zaude/main/install/install.ps1 | iex
```

The scripts do the same work but non-interactively (prompts instead of AI-driven Q&A). Choose whichever feels better.
