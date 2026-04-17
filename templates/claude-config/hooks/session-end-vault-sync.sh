#!/bin/bash
# Zaude — SessionEnd hook.
#
# Responsibilities (in order):
#   1. Auto-commit and push the vault and the Claude-config repos if they
#      have pending changes.
#   2. If config.auto_sync is true AND the Claude-config push touched any
#      framework file (hooks, commands, settings.json, global CLAUDE.md),
#      OR the vault patterns directory changed, trigger zaude-sync.sh in
#      non-interactive mode to open a PR against the Zaude repo.
#
# Reads paths from ~/.zaude/config.json (vault_path, claude_config_path,
# zaude_repo_path, auto_sync). Never fails session end — every failure is
# logged and swallowed.

LOG="$HOME/.claude/hooks/session-end-vault-sync.log"
CONFIG="$HOME/.zaude/config.json"

read_config_field() {
  local field="$1"
  local value
  if [ ! -f "$CONFIG" ]; then
    echo ""
    return
  fi
  # Normalize config path for Windows Python (Git Bash /c/... is not valid).
  local config_norm="$CONFIG"
  if command -v cygpath >/dev/null 2>&1; then
    config_norm="$(cygpath -m "$CONFIG")"
  fi
  if command -v python3 >/dev/null 2>&1; then
    value=$(ZAUDE_CONFIG_PATH="$config_norm" ZAUDE_FIELD="$field" python3 -c "import json,os; c=json.load(open(os.environ['ZAUDE_CONFIG_PATH'],encoding='utf-8')); v=c.get(os.environ['ZAUDE_FIELD'],''); print(os.path.expanduser(str(v)) if isinstance(v,str) else str(v).lower())" 2>/dev/null)
  elif command -v python >/dev/null 2>&1; then
    value=$(ZAUDE_CONFIG_PATH="$config_norm" ZAUDE_FIELD="$field" python -c "import json,os; c=json.load(open(os.environ['ZAUDE_CONFIG_PATH'],encoding='utf-8')); v=c.get(os.environ['ZAUDE_FIELD'],''); print(os.path.expanduser(str(v)) if isinstance(v,str) else str(v).lower())" 2>/dev/null)
  else
    value=$(grep -oE "\"$field\"\s*:\s*\"[^\"]+\"" "$CONFIG" | sed -E "s/.*\"$field\"\s*:\s*\"([^\"]+)\".*/\1/" | head -1)
    value="${value/#\~/$HOME}"
  fi
  echo "$value"
}

# Returns 0 if the committed changes in the given repo touched any framework
# path. Used to decide whether to run zaude-sync.
recent_commit_touched_framework() {
  local repo="$1"
  cd "$repo" 2>/dev/null || return 1
  # Check the most recent commit's file list.
  local files
  files=$(git show --name-only --pretty=format: HEAD 2>/dev/null || echo "")
  echo "$files" | grep -qE '^(commands/|hooks/|settings\.json|CLAUDE\.md|\.claude/commands/|\.claude/hooks/|03-patterns/|03-ultahost-patterns/)' && return 0
  return 1
}

sync_repo() {
  local repo_path="$1"
  local repo_label="$2"

  echo "--- syncing ${repo_label} (${repo_path}) ---"

  if [ -z "$repo_path" ] || [ ! -d "$repo_path" ]; then
    echo "${repo_label}: path not set or directory not found, skipping"
    return 1
  fi

  cd "$repo_path" || { echo "${repo_label}: cd failed"; return 1; }

  if [ ! -d .git ]; then
    echo "${repo_label}: not a git repo, skipping"
    return 1
  fi

  git add -A 2>&1

  if git diff --cached --quiet 2>/dev/null; then
    echo "${repo_label}: no staged changes, nothing to commit"
    return 1  # nothing changed -> don't trigger downstream sync
  fi

  git commit -m "auto-commit $(date +%F-%H%M)" 2>&1 || {
    echo "${repo_label}: commit failed, leaving staged"
    return 1
  }

  git push 2>&1 || {
    echo "${repo_label}: push failed, commit kept locally"
    return 1
  }

  echo "${repo_label}: synced"
  return 0
}

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') session-end sync ==="

  VAULT_PATH=$(read_config_field vault_path)
  CLAUDE_CONFIG_PATH=$(read_config_field claude_config_path)
  ZAUDE_REPO_PATH=$(read_config_field zaude_repo_path)
  AUTO_SYNC=$(read_config_field auto_sync)

  vault_changed=0
  config_changed=0

  if sync_repo "$VAULT_PATH" "vault"; then
    vault_changed=1
  fi
  if [ -n "$CLAUDE_CONFIG_PATH" ] && sync_repo "$CLAUDE_CONFIG_PATH" "claude-config"; then
    config_changed=1
  fi

  # Auto-sync to Zaude if enabled, and if something relevant changed.
  if [ "$AUTO_SYNC" = "true" ] && [ -n "$ZAUDE_REPO_PATH" ]; then
    trigger=0
    if [ "$config_changed" -eq 1 ] && recent_commit_touched_framework "$CLAUDE_CONFIG_PATH"; then
      trigger=1
      echo "auto_sync: claude-config commit touched framework files"
    fi
    if [ "$vault_changed" -eq 1 ] && recent_commit_touched_framework "$VAULT_PATH"; then
      trigger=1
      echo "auto_sync: vault commit touched pattern files"
    fi

    if [ "$trigger" -eq 1 ]; then
      echo "auto_sync: triggering zaude-sync.sh --yes"
      sync_script="$ZAUDE_REPO_PATH/install/zaude-sync.sh"
      if [ -f "$sync_script" ]; then
        bash "$sync_script" --yes 2>&1 || echo "auto_sync: zaude-sync exited non-zero; see above"
      else
        echo "auto_sync: $sync_script not found — skipping"
      fi
    else
      echo "auto_sync: no framework changes, skipping zaude-sync"
    fi
  fi
} >> "$LOG" 2>&1

exit 0
