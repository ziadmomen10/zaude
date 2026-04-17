#!/bin/bash
# Zaude — SessionEnd hook.
#
# Auto-commits and pushes both the vault and the Claude-config repos if
# they have pending changes. Reads paths from ~/.zaude/config.json (fields:
# vault_path, claude_config_path). Never fails session end — every failure
# is logged and swallowed.

LOG="$HOME/.claude/hooks/session-end-vault-sync.log"
CONFIG="$HOME/.zaude/config.json"

read_config_path() {
  local field="$1"
  local value
  if [ ! -f "$CONFIG" ]; then
    echo ""
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    value=$(python3 -c "import json,os,sys; c=json.load(open(os.path.expanduser('$CONFIG'))); print(os.path.expanduser(c.get('$field','')))" 2>/dev/null)
  elif command -v python >/dev/null 2>&1; then
    value=$(python -c "import json,os,sys; c=json.load(open(os.path.expanduser('$CONFIG'))); print(os.path.expanduser(c.get('$field','')))" 2>/dev/null)
  else
    value=$(grep -oE "\"$field\"\s*:\s*\"[^\"]+\"" "$CONFIG" | sed -E "s/.*\"$field\"\s*:\s*\"([^\"]+)\".*/\1/" | head -1)
    value="${value/#\~/$HOME}"
  fi
  echo "$value"
}

sync_repo() {
  local repo_path="$1"
  local repo_label="$2"

  echo "--- syncing ${repo_label} (${repo_path}) ---"

  if [ -z "$repo_path" ] || [ ! -d "$repo_path" ]; then
    echo "${repo_label}: path not set or directory not found, skipping"
    return
  fi

  cd "$repo_path" || { echo "${repo_label}: cd failed"; return; }

  if [ ! -d .git ]; then
    echo "${repo_label}: not a git repo, skipping"
    return
  fi

  git add -A 2>&1

  if git diff --cached --quiet 2>/dev/null; then
    echo "${repo_label}: no staged changes, nothing to commit"
    return
  fi

  git commit -m "auto-commit $(date +%F-%H%M)" 2>&1 || {
    echo "${repo_label}: commit failed, leaving staged"
    return
  }

  git push 2>&1 || {
    echo "${repo_label}: push failed, commit kept locally"
    return
  }

  echo "${repo_label}: synced"
}

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') session-end sync ==="
  VAULT_PATH="$(read_config_path vault_path)"
  CLAUDE_CONFIG_PATH="$(read_config_path claude_config_path)"
  sync_repo "$VAULT_PATH" "vault"
  [ -n "$CLAUDE_CONFIG_PATH" ] && sync_repo "$CLAUDE_CONFIG_PATH" "claude-config"
} >> "$LOG" 2>&1

exit 0
