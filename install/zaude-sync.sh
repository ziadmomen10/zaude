#!/usr/bin/env bash
# Zaude sync — propagate local framework edits back to the Zaude repo as a PR.
#
# What it does:
#   1. Reads ~/.zaude/config.json to find the local Zaude repo clone + your vault
#   2. Diffs your local framework files (hooks, commands, patterns, settings.json,
#      CLAUDE.md) against the Zaude repo's main branch
#   3. Runs a genericization lint — scans the DIFF (new lines only) for private
#      markers you've listed (company name, internal VPS IPs, project slugs). If
#      anything hits, aborts BEFORE creating a branch. Nothing goes public.
#   4. If the diff is clean, creates a branch `sync-YYYY-MM-DD-HHMMSS` on the
#      Zaude repo, commits the changes, pushes, opens a PR via `gh`.
#
# Safety design:
#   - PR-only by default. Never commits to main.
#   - Genericization lint runs BEFORE any push. Private content never reaches remote.
#   - No files are copied from the Zaude repo back into your local setup — this
#     is one-directional (local → Zaude PR).
#   - Respects a sync_exclude list in config.json for paths you never want to sync.
#
# Config keys (in ~/.zaude/config.json):
#   zaude_repo_path         — absolute path to your local Zaude clone (required)
#   sync_private_markers    — list of strings that abort sync if found in diff
#                             (default: a sensible baseline)
#   sync_exclude            — list of path patterns to never sync (default: [])
#   auto_sync               — bool; if true, SessionEnd hook calls this script
#                             (default: false)
#
# Exit codes:
#   0 — success (PR opened, or nothing to sync)
#   1 — config missing or invalid
#   2 — genericization lint failed (private content detected)
#   3 — git/gh error
#
# Usage:
#   bash zaude-sync.sh                  # interactive: shows plan, asks to proceed
#   bash zaude-sync.sh --yes            # non-interactive: proceed without asking
#   bash zaude-sync.sh --dry-run        # show what WOULD be synced; no push
#   bash zaude-sync.sh --lint-only      # run the genericization lint and exit

set -euo pipefail

# ─── colors ─────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  RESET=$'\033[0m'; BOLD=$'\033[1m'; DIM=$'\033[2m'
  CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'
else
  RESET=""; BOLD=""; DIM=""; CYAN=""; GREEN=""; YELLOW=""; RED=""
fi

say()  { echo -e "${CYAN}▸${RESET} $*"; }
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*" >&2; }

# ─── args ───────────────────────────────────────────────────────────────────
NONINTERACTIVE=0
DRY_RUN=0
LINT_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)     NONINTERACTIVE=1 ;;
    --dry-run)    DRY_RUN=1 ;;
    --lint-only)  LINT_ONLY=1 ;;
    -h|--help)
      sed -n '2,35p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) err "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ─── config ─────────────────────────────────────────────────────────────────
CONFIG="$HOME/.zaude/config.json"
if [ ! -f "$CONFIG" ]; then
  err "No config at $CONFIG. Run Zaude's installer first."
  exit 1
fi

PYCMD=$(command -v python3 || command -v python)
if [ -z "$PYCMD" ]; then
  err "python3 or python required on PATH."
  exit 1
fi

# Normalize the config path so Python can open it on Windows (Git Bash's
# /c/... format is not recognized by the Windows Python interpreter).
if command -v cygpath >/dev/null 2>&1; then
  CONFIG_NORM="$(cygpath -m "$CONFIG")"
else
  CONFIG_NORM="$CONFIG"
fi

# Export so the Python heredoc can reach them via env.
export ZAUDE_CONFIG_PATH="$CONFIG_NORM"

read_config_field() {
  ZAUDE_FIELD="$1" "$PYCMD" -c "
import json, os, sys
path = os.environ['ZAUDE_CONFIG_PATH']
field = os.environ['ZAUDE_FIELD']
with open(path, encoding='utf-8') as f:
    c = json.load(f)
v = c.get(field)
if isinstance(v, (list, dict)):
    print(json.dumps(v))
elif v is None:
    print('')
else:
    print(os.path.expanduser(str(v)))
"
}

ZAUDE_REPO_PATH=$(read_config_field zaude_repo_path)
VAULT_PATH=$(read_config_field vault_path)
CLAUDE_CONFIG_PATH=$(read_config_field claude_config_path)
PATTERNS_SUBDIR=$(read_config_field patterns_subdir)
[ -z "$CLAUDE_CONFIG_PATH" ] && CLAUDE_CONFIG_PATH="$HOME/.claude"
[ -z "$PATTERNS_SUBDIR" ] && PATTERNS_SUBDIR="03-patterns"

# Read sync_exclude list (paths relative to ~/.claude/ or vault/)
EXCLUDE_JSON=$(read_config_field sync_exclude)
SYNC_EXCLUDE=()
if [ -n "$EXCLUDE_JSON" ] && [ "$EXCLUDE_JSON" != "[]" ] && [ "$EXCLUDE_JSON" != "" ]; then
  while IFS= read -r line; do
    # Strip trailing \r on Windows (Python's print adds \r\n on MSYS/Git-Bash pipe).
    line="${line%$'\r'}"
    [ -n "$line" ] && SYNC_EXCLUDE+=("$line")
  done < <(ZAUDE_JSON="$EXCLUDE_JSON" "$PYCMD" -c "import json, os; [print(x) for x in json.loads(os.environ['ZAUDE_JSON'])]" 2>/dev/null)
fi

# Returns 0 (excluded) if the given relative path matches an entry in
# SYNC_EXCLUDE. The match is substring-based on the relative path under
# ~/.claude/ or the vault (e.g. 'commands/ship.md', '03-patterns/foo.md').
is_excluded() {
  local rel="$1"
  for pattern in "${SYNC_EXCLUDE[@]}"; do
    [ -z "$pattern" ] && continue
    [[ "$rel" == *"$pattern"* ]] && return 0
  done
  return 1
}

if [ -z "$ZAUDE_REPO_PATH" ] || [ ! -d "$ZAUDE_REPO_PATH" ]; then
  err "zaude_repo_path not set in $CONFIG (or path does not exist)."
  err "Set it to your local clone of the Zaude repo, e.g.:"
  err "   \"zaude_repo_path\": \"\$HOME/zaude\""
  exit 1
fi

# ─── genericization lint ─────────────────────────────────────────────────────
# Default private markers — things that should never appear in a public Zaude
# commit. Users can extend via config.sync_private_markers.
DEFAULT_MARKERS=(
  "UltaHost"
  "ultahost"
  "UltaHost-Vault"
  "host-once-hub"
  "host-once-platform"
  "devops-control-center"
  "devops-dashboard"
  "ulta2024"
  "@ultahost.com"
)

# Custom markers from config
CUSTOM_MARKERS_JSON=$(read_config_field sync_private_markers)
if [ -n "$CUSTOM_MARKERS_JSON" ] && [ "$CUSTOM_MARKERS_JSON" != "" ]; then
  # Parse JSON array into bash array
  readarray -t CUSTOM_MARKERS < <("$PYCMD" -c "
import json, sys
markers = json.loads('''$CUSTOM_MARKERS_JSON''')
for m in markers:
    print(m)
")
else
  CUSTOM_MARKERS=()
fi

ALL_MARKERS=("${DEFAULT_MARKERS[@]}" "${CUSTOM_MARKERS[@]}")

# Also: IP patterns (rough match for 3-4 octets)
IP_REGEX='\b([0-9]{1,3}\.){3}[0-9]{1,3}\b'

# ─── stage framework files into a scratch copy ──────────────────────────────
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT

say "Staging local framework files for diff..."

# Files we sync:
#   commands/*.md             ← ~/.claude/commands/*.md
#   hooks/*.py *.sh           ← ~/.claude/hooks/*.{py,sh}  (excluding logs)
#   settings.json             ← ~/.claude/settings.json
#   CLAUDE.md                 ← ~/.claude/CLAUDE.md   (careful — may be personal)
#   vault/03-patterns/*.md    ← $VAULT_PATH/$PATTERNS_SUBDIR/*.md
#
# Files we DO NOT sync:
#   config.sample.json        ← that's the canonical template; don't overwrite from user
#   any vault project content, decisions, sessions, credentials

# commands
mkdir -p "$SCRATCH/templates/claude-config/commands"
if ls "$CLAUDE_CONFIG_PATH/commands/"*.md >/dev/null 2>&1; then
  # Only sync the 5 Zaude commands — not third-party ones that may be installed.
  for cmd in start build review ship wrap zaude-push; do
    relpath="commands/$cmd.md"
    if [ -f "$CLAUDE_CONFIG_PATH/$relpath" ] && ! is_excluded "$relpath"; then
      cp "$CLAUDE_CONFIG_PATH/$relpath" "$SCRATCH/templates/claude-config/$relpath"
    fi
  done
fi

# hooks
mkdir -p "$SCRATCH/templates/claude-config/hooks"
for hook in session-start-vault.py session-end-vault-sync.sh frozen-guard.py; do
  relpath="hooks/$hook"
  if [ -f "$CLAUDE_CONFIG_PATH/$relpath" ] && ! is_excluded "$relpath"; then
    cp "$CLAUDE_CONFIG_PATH/$relpath" "$SCRATCH/templates/claude-config/$relpath"
  fi
done

# settings.json
if [ -f "$CLAUDE_CONFIG_PATH/settings.json" ] && ! is_excluded "settings.json"; then
  cp "$CLAUDE_CONFIG_PATH/settings.json" "$SCRATCH/templates/claude-config/settings.json"
fi

# global CLAUDE.md
if [ -f "$CLAUDE_CONFIG_PATH/CLAUDE.md" ] && ! is_excluded "CLAUDE.md"; then
  cp "$CLAUDE_CONFIG_PATH/CLAUDE.md" "$SCRATCH/templates/claude-config/CLAUDE.md"
fi

# vault patterns
if [ -n "$VAULT_PATH" ] && [ -d "$VAULT_PATH/$PATTERNS_SUBDIR" ]; then
  mkdir -p "$SCRATCH/templates/vault/03-patterns"
  for f in "$VAULT_PATH/$PATTERNS_SUBDIR"/*.md; do
    [ -f "$f" ] || continue
    relpath="03-patterns/$(basename "$f")"
    if ! is_excluded "$relpath"; then
      cp "$f" "$SCRATCH/templates/vault/03-patterns/$(basename "$f")"
    fi
  done
fi

# ─── compute diff against Zaude repo main ───────────────────────────────────
say "Comparing against Zaude repo main branch..."

cd "$ZAUDE_REPO_PATH"
git fetch origin main --quiet 2>/dev/null || { err "Could not fetch origin/main in $ZAUDE_REPO_PATH"; exit 3; }

# Use a unified-diff output to show what's changing. Diff the scratch copy
# against the tree at origin/main.
DIFF_REPORT="$SCRATCH/diff.patch"
: > "$DIFF_REPORT"

staged_paths=()
while IFS= read -r -d '' file; do
  rel="${file#$SCRATCH/}"
  # Only known-safe target paths:
  case "$rel" in
    templates/claude-config/commands/*.md | \
    templates/claude-config/hooks/*.py | \
    templates/claude-config/hooks/*.sh | \
    templates/claude-config/settings.json | \
    templates/claude-config/CLAUDE.md | \
    templates/vault/03-patterns/*.md)
      ;;
    *)
      continue
      ;;
  esac

  # Compare scratch file against the version in origin/main
  remote_content=$(git show "origin/main:$rel" 2>/dev/null || echo "__ZAUDE_MISSING__")
  local_content=$(cat "$file")

  if [ "$remote_content" = "__ZAUDE_MISSING__" ]; then
    # New file
    echo "--- a/$rel" >> "$DIFF_REPORT"
    echo "+++ b/$rel (NEW)" >> "$DIFF_REPORT"
    sed 's/^/+/' "$file" >> "$DIFF_REPORT"
    echo "" >> "$DIFF_REPORT"
    staged_paths+=("$rel:$file")
  elif [ "$local_content" != "$remote_content" ]; then
    echo "--- a/$rel" >> "$DIFF_REPORT"
    echo "+++ b/$rel" >> "$DIFF_REPORT"
    diff -u <(echo "$remote_content") <(echo "$local_content") | tail -n +3 >> "$DIFF_REPORT" || true
    echo "" >> "$DIFF_REPORT"
    staged_paths+=("$rel:$file")
  fi
done < <(find "$SCRATCH" -type f -print0)

if [ ${#staged_paths[@]} -eq 0 ]; then
  ok "Nothing to sync. Local framework matches Zaude main."
  exit 0
fi

say "${#staged_paths[@]} file(s) differ from Zaude main:"
for sp in "${staged_paths[@]}"; do
  echo "   ${sp%%:*}"
done

# ─── genericization lint ────────────────────────────────────────────────────
echo ""
say "Running genericization lint on the diff (new/changed content only)..."

LINT_HITS=""
# Extract only added lines (lines starting with "+" but not "+++" headers)
added_lines=$(grep -E '^\+[^+]' "$DIFF_REPORT" || true)

if [ -n "$added_lines" ]; then
  for marker in "${ALL_MARKERS[@]}"; do
    [ -z "$marker" ] && continue
    hit=$(echo "$added_lines" | grep -F "$marker" | head -5 || true)
    if [ -n "$hit" ]; then
      LINT_HITS+="\n  ${RED}MARKER:${RESET} '$marker' found in added content:\n"
      LINT_HITS+="$(echo "$hit" | sed 's/^/    /')\n"
    fi
  done

  # IP pattern check — only flag non-common ones (ignore 127.0.0.1, 0.0.0.0, 255.*,
  # and classic RFC 5737 doc ranges)
  ip_hits=$(echo "$added_lines" | grep -oE "$IP_REGEX" | \
    grep -vE '^(127\.0\.0\.1|0\.0\.0\.0|255\.255\.255\.255|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|10\.0\.0\.1)$' | \
    sort -u | head -5 || true)
  if [ -n "$ip_hits" ]; then
    LINT_HITS+="\n  ${RED}IP ADDRESS:${RESET} non-standard IPs in added content (may be internal):\n"
    LINT_HITS+="$(echo "$ip_hits" | sed 's/^/    /')\n"
  fi
fi

if [ -n "$LINT_HITS" ]; then
  echo ""
  err "Genericization lint FAILED. Private content detected in the diff:"
  echo -e "$LINT_HITS"
  echo ""
  err "Sync aborted. Nothing was pushed. Options:"
  err "  1. Edit the offending files to remove the private markers, then re-run."
  err "  2. Add the marker to 'sync_private_markers' in ~/.zaude/config.json"
  err "     if it's a legitimate framework token that happens to match a marker."
  err "  3. If the file should never sync, add it to 'sync_exclude'."
  exit 2
fi

ok "Lint passed. No private markers in the diff."

if [ $LINT_ONLY -eq 1 ]; then
  ok "Lint-only mode — exiting without sync."
  exit 0
fi

# ─── preview ─────────────────────────────────────────────────────────────────
echo ""
say "Diff preview (first 60 lines):"
head -60 "$DIFF_REPORT" | sed 's/^/   /'
echo ""

if [ $DRY_RUN -eq 1 ]; then
  ok "Dry-run — exiting without push."
  exit 0
fi

# ─── confirm ─────────────────────────────────────────────────────────────────
if [ $NONINTERACTIVE -eq 0 ]; then
  read -rp "${BOLD}Create sync branch and open PR?${RESET} [y/N]: " ans
  if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    warn "Aborted by user. Nothing pushed."
    exit 0
  fi
fi

# ─── branch + commit + push + PR ─────────────────────────────────────────────
BRANCH="sync-$(date +%Y%m%d-%H%M%S)"

cd "$ZAUDE_REPO_PATH"

# Make sure working tree is clean so we can branch off main cleanly
if ! git diff-index --quiet HEAD --; then
  err "Zaude repo has uncommitted changes. Commit or stash first."
  exit 3
fi

git checkout -q -B "$BRANCH" origin/main 2>&1 | tail -2

# Apply staged files
for sp in "${staged_paths[@]}"; do
  rel="${sp%%:*}"
  src="${sp#*:}"
  mkdir -p "$(dirname "$ZAUDE_REPO_PATH/$rel")"
  cp "$src" "$ZAUDE_REPO_PATH/$rel"
done

git add -A

if git diff --cached --quiet; then
  warn "After staging, no changes detected. Cleaning up."
  git checkout -q main
  git branch -D "$BRANCH" >/dev/null 2>&1 || true
  exit 0
fi

commit_msg="sync: auto-update framework from local edits ($(date +%F))"
git -c user.email="${GIT_USER_EMAIL:-ziad.momen@ultahost.com}" \
    -c user.name="${GIT_USER_NAME:-Ziad Momen}" \
    commit -m "$commit_msg" --quiet

say "Pushing branch $BRANCH..."
git push -u origin "$BRANCH" --quiet 2>&1 | tail -3

# Open PR
if command -v gh >/dev/null 2>&1; then
  pr_body="Automated sync from local framework edits.

**Summary:** $(printf '%s\n' "${staged_paths[@]}" | wc -l | tr -d ' ') file(s) changed.

**Files:**
$(for sp in "${staged_paths[@]}"; do echo "- \`${sp%%:*}\`"; done)

**Genericization lint:** ✅ passed (no private markers detected in diff)

**To review:** open the Files tab on this PR. Each change is a file you edited locally since the last sync. If any change looks wrong or includes content that should not be public, close this PR and re-run \`zaude-sync.sh --lint-only\` after fixing.

**To ship:** approve and merge. The next session-start elsewhere will pick up the new templates on the next \`git pull\` of this repo.

🤖 Generated with Zaude auto-sync."

  PR_URL=$(gh pr create --title "$commit_msg" --body "$pr_body" --head "$BRANCH" --base main 2>&1 | tail -1)
  ok "PR opened: $PR_URL"
else
  warn "gh CLI not available — branch pushed, but PR not created automatically."
  warn "Visit your Zaude repo on GitHub to open a PR from $BRANCH → main."
fi

# Return to main
git checkout -q main

ok "Sync complete."
