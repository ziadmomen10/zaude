#!/usr/bin/env bash
# Zaude installer — macOS / Linux / WSL.
# Non-interactive alternative to install/setup-prompt.md.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ziadmomen10/zaude/main/install/install.sh | bash
#   (or) bash install.sh

set -euo pipefail

REPO_URL="https://github.com/ziadmomen10/zaude.git"
REPO_RAW="https://raw.githubusercontent.com/ziadmomen10/zaude/main"

# ---- ansi colors (only if terminal) ----
if [ -t 1 ]; then
  RESET=$'\033[0m'; BOLD=$'\033[1m'; DIM=$'\033[2m'
  CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'
else
  RESET=""; BOLD=""; DIM=""; CYAN=""; GREEN=""; YELLOW=""; RED=""
fi

say() { echo -e "${CYAN}▸${RESET} $*"; }
ok()  { echo -e "${GREEN}✓${RESET} $*"; }
warn(){ echo -e "${YELLOW}!${RESET} $*"; }
die() { echo -e "${RED}✗${RESET} $*" >&2; exit 1; }

banner() {
  cat <<'BANNER'

   ╔══════════════════════════════════════════╗
   ║                                          ║
   ║   ███████╗ █████╗ ██╗   ██╗██████╗ ███████╗
   ║   ╚══███╔╝██╔══██╗██║   ██║██╔══██╗██╔════╝
   ║     ███╔╝ ███████║██║   ██║██║  ██║█████╗
   ║    ███╔╝  ██╔══██║██║   ██║██║  ██║██╔══╝
   ║   ███████╗██║  ██║╚██████╔╝██████╔╝███████╗
   ║   ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝
   ║                                          ║
   ║      Don't vibe code. Zaude code.        ║
   ╚══════════════════════════════════════════╝

BANNER
}

# ---- prereqs ----
require() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required but not found on PATH."
}

banner
say "Checking prerequisites..."
require git
require python3
require bash
command -v gh >/dev/null 2>&1 || warn "gh CLI not found — GitHub repo creation will be skipped. Install from https://cli.github.com for full experience."
ok "Prerequisites OK."

# ---- interactive prompts ----
ask() {
  local prompt="$1" default="$2" answer
  read -rp "$(echo -e "${BOLD}$prompt${RESET}${DIM}${default:+ [$default]}${RESET}: ")" answer
  echo "${answer:-$default}"
}

ask_yes_no() {
  local prompt="$1" default="${2:-n}" answer
  read -rp "$(echo -e "${BOLD}$prompt${RESET} ${DIM}[y/N]${RESET}: ")" answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy]$ ]]
}

VAULT_PATH=$(ask "Where should your vault live?" "$HOME/zaude-vault")
VAULT_PATH="${VAULT_PATH/#\~/$HOME}"

GH_USER=""
if command -v gh >/dev/null 2>&1; then
  GH_USER=$(gh api user --jq .login 2>/dev/null || echo "")
  if [ -z "$GH_USER" ]; then
    warn "gh is installed but not authenticated. Run: gh auth login"
  fi
fi
GH_USER=$(ask "GitHub username for private repos" "$GH_USER")

PROJECT_SLUG=$(ask "First project slug (lowercase-with-dashes)" "my-first-project")
PROJECT_CWD=$(ask "Current working directory for that project (absolute path)" "$HOME/$PROJECT_SLUG")
PROJECT_CWD="${PROJECT_CWD/#\~/$HOME}"
PROJECT_CWD_BASE=$(basename "$PROJECT_CWD")

FROZEN_ZONES=$(ask "Frozen path substrings (comma-separated, or blank for none)" "")

# ---- clone zaude ----
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
say "Cloning Zaude into $TMPDIR..."
git clone --depth 1 "$REPO_URL" "$TMPDIR/zaude" >/dev/null 2>&1 \
  || die "Could not clone $REPO_URL. Check your network / the repo URL."
ok "Cloned."

# ---- create vault ----
say "Creating vault at $VAULT_PATH..."
if [ -d "$VAULT_PATH" ]; then
  ask_yes_no "Vault directory exists. Overwrite non-clashing files only (safe)?" "y" \
    || die "Aborted by user."
fi
mkdir -p "$VAULT_PATH"
cp -R "$TMPDIR/zaude/templates/vault/." "$VAULT_PATH/"

# Rename _template to the project slug
if [ -d "$VAULT_PATH/01-projects/_template" ]; then
  mv "$VAULT_PATH/01-projects/_template" "$VAULT_PATH/01-projects/$PROJECT_SLUG"
fi
ok "Vault scaffolded. First project: $PROJECT_SLUG"

# ---- install claude-config ----
CLAUDE_DIR="$HOME/.claude"
mkdir -p "$CLAUDE_DIR/commands" "$CLAUDE_DIR/hooks"

say "Installing hooks into $CLAUDE_DIR/hooks..."
for f in "$TMPDIR/zaude/templates/claude-config/hooks/"*; do
  dest="$CLAUDE_DIR/hooks/$(basename "$f")"
  if [ -e "$dest" ]; then
    ask_yes_no "  $dest exists. Overwrite?" "n" && cp "$f" "$dest"
  else
    cp "$f" "$dest"
  fi
done
chmod +x "$CLAUDE_DIR/hooks/"*.py "$CLAUDE_DIR/hooks/"*.sh 2>/dev/null || true
ok "Hooks installed."

say "Installing commands into $CLAUDE_DIR/commands..."
for f in "$TMPDIR/zaude/templates/claude-config/commands/"*.md; do
  dest="$CLAUDE_DIR/commands/$(basename "$f")"
  if [ -e "$dest" ]; then
    ask_yes_no "  $dest exists. Overwrite?" "n" && cp "$f" "$dest"
  else
    cp "$f" "$dest"
  fi
done
ok "Commands installed."

# settings.json merge
SETTINGS="$CLAUDE_DIR/settings.json"
if [ ! -f "$SETTINGS" ]; then
  cp "$TMPDIR/zaude/templates/claude-config/settings.json" "$SETTINGS"
  ok "settings.json created."
else
  warn "$SETTINGS already exists. Zaude won't overwrite it."
  warn "Compare against templates/claude-config/settings.json and merge the hook entries manually."
fi

# global CLAUDE.md
GLOBAL_MD="$CLAUDE_DIR/CLAUDE.md"
if [ ! -f "$GLOBAL_MD" ]; then
  cp "$TMPDIR/zaude/templates/claude-config/CLAUDE.md" "$GLOBAL_MD"
  ok "Global CLAUDE.md created."
else
  warn "$GLOBAL_MD exists. Appending Zaude section with a separator."
  {
    echo ""
    echo "---"
    echo ""
    echo "<!-- Zaude framework — appended by install.sh $(date +%F) -->"
    cat "$TMPDIR/zaude/templates/claude-config/CLAUDE.md"
  } >> "$GLOBAL_MD"
fi

# ---- zaude config ----
mkdir -p "$HOME/.zaude"
CONFIG="$HOME/.zaude/config.json"

# Build JSON via python for safe quoting
python3 - "$CONFIG" "$VAULT_PATH" "$CLAUDE_DIR" "$PROJECT_CWD_BASE" "$PROJECT_SLUG" "$FROZEN_ZONES" <<'PY'
import json, os, sys
config_path, vault, claude, cwd_base, slug, frozen_csv = sys.argv[1:7]
frozen = [z.strip() for z in frozen_csv.split(",") if z.strip()]
cfg = {
    "vault_path": vault,
    "projects_subdir": "01-projects",
    "patterns_subdir": "03-patterns",
    "cwd_to_project": {cwd_base: slug} if cwd_base and slug else {},
    "frozen_zones": frozen,
    "recent_session_logs": 3,
    "claude_config_path": claude,
}
os.makedirs(os.path.dirname(config_path), exist_ok=True)
with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
ok "Wrote $CONFIG"

# ---- github repos ----
if command -v gh >/dev/null 2>&1 && [ -n "$GH_USER" ]; then
  if ask_yes_no "Create private GitHub repos for vault + claude-config?" "y"; then
    say "Creating github.com/$GH_USER/zaude-vault (private)..."
    gh repo create "$GH_USER/zaude-vault" --private --description "My Zaude vault" 2>/dev/null || warn "Vault repo already exists or create failed."

    say "Creating github.com/$GH_USER/zaude-claude-config (private)..."
    gh repo create "$GH_USER/zaude-claude-config" --private --description "My Zaude Claude-Code config" 2>/dev/null || warn "Config repo already exists or create failed."

    # init vault
    say "Initializing vault git repo..."
    ( cd "$VAULT_PATH" && git init -b main -q && git add -A && git -c user.email="$(git config --global user.email 2>/dev/null || echo you@example.com)" commit -m "Initial Zaude vault" -q )
    ( cd "$VAULT_PATH" && git remote add origin "https://github.com/$GH_USER/zaude-vault.git" 2>/dev/null || true )
    ( cd "$VAULT_PATH" && git push -u origin main -q ) && ok "Vault pushed."

    # init claude-config with curated gitignore
    say "Initializing ~/.claude git repo with curated .gitignore..."
    if [ ! -d "$CLAUDE_DIR/.git" ]; then
      cp "$TMPDIR/zaude/templates/claude-config/.gitignore" "$CLAUDE_DIR/.gitignore" 2>/dev/null || {
        # fallback: write inline gitignore
        cat > "$CLAUDE_DIR/.gitignore" <<'GITIGNORE'
*
!commands/
!commands/**
!hooks/
!hooks/**
!agents/
!agents/**
!skills/
!skills/**
!CLAUDE.md
!settings.json
!.gitignore
!README.md
!projects/
!projects/*/
!projects/*/memory/
!projects/*/memory/**
**/*.log
**/*.credentials.json
**/.credentials.json
GITIGNORE
      }
      ( cd "$CLAUDE_DIR" && git init -b main -q )
    fi
    ( cd "$CLAUDE_DIR" && git add -A )
    if ( cd "$CLAUDE_DIR" && git diff --cached --quiet ); then
      warn "Nothing to commit in ~/.claude."
    else
      ( cd "$CLAUDE_DIR" && git -c user.email="$(git config --global user.email 2>/dev/null || echo you@example.com)" commit -m "Initial Zaude-installed config" -q )
      ( cd "$CLAUDE_DIR" && git remote add origin "https://github.com/$GH_USER/zaude-claude-config.git" 2>/dev/null || true )
      ( cd "$CLAUDE_DIR" && git push -u origin main -q ) && ok "Claude-config pushed."
    fi
  fi
else
  warn "Skipping GitHub repo creation (gh not installed or not authenticated)."
fi

# ---- optional: v0.5 VoltAgent specialists ----
install_voltagent_v05() {
  local agents_dir="$CLAUDE_DIR/agents"
  mkdir -p "$agents_dir"

  say "Cloning VoltAgent awesome-claude-code-subagents..."
  local voltagent_tmp="$TMPDIR/voltagent"
  if ! git clone --depth 1 "https://github.com/VoltAgent/awesome-claude-code-subagents.git" "$voltagent_tmp" >/dev/null 2>&1; then
    warn "Could not clone VoltAgent repo. Skipping v0.5 agent install — you can run the manual awk loop from docs/08-agents.md later."
    return 1
  fi

  # Canonical v0.5 specialist roster — keep in sync with .github/ci/verify-agent-docs.py
  local all_agents=(
    debugger postgres-pro sql-pro python-pro prompt-engineer refactoring-specialist
    react-specialist docker-expert documentation-engineer accessibility-tester mcp-developer
  )

  # Agents whose source declares Write/Edit and therefore need a -readonly variant.
  # accessibility-tester is already read-only at source — no variant generated.
  local readonly_variants=(
    debugger postgres-pro sql-pro python-pro prompt-engineer refactoring-specialist
    react-specialist docker-expert documentation-engineer mcp-developer
  )

  local manifest="$agents_dir/.zaude-manifest"
  {
    echo "# Zaude-installed VoltAgent v0.5 agents"
    echo "# Generated by install.sh on $(date +%F)"
    echo "# Format: <filename> (one per line)"
    echo "# Used for clean uninstall: rm \$(grep -v '^#' $manifest | xargs -I{} echo $agents_dir/{})"
  } > "$manifest"

  local installed=0
  local missing=()
  for agent in "${all_agents[@]}"; do
    local src
    src=$(find "$voltagent_tmp" -name "${agent}.md" -print -quit 2>/dev/null || true)
    if [ -z "$src" ]; then
      missing+=("$agent")
      continue
    fi
    cp "$src" "$agents_dir/${agent}.md"
    echo "${agent}.md" >> "$manifest"
    installed=$((installed + 1))
  done

  if [ ${#missing[@]} -gt 0 ]; then
    warn "  Agents not found in VoltAgent repo (may have been renamed upstream): ${missing[*]}"
  fi

  # Generate -readonly variants (portable awk — GNU/BSD compatible)
  local variants_generated=0
  for agent in "${readonly_variants[@]}"; do
    local src="$agents_dir/${agent}.md"
    local dst="$agents_dir/${agent}-readonly.md"
    [ -f "$src" ] || continue

    awk -v agent="$agent" '
      BEGIN { fm = 0; done_preamble = 0 }
      /^---$/ {
        fm++
        print
        if (fm == 2 && !done_preamble) {
          print ""
          print "> **Zaude read-only mode.** You are invoked by a Zaude command that forbids source-file mutation. Do NOT attempt to write or edit files — your declared tool surface does not permit it, and the command'"'"'s sandbox will block any such attempt. Produce findings, plans, and recommendations only. A separate implementation agent applies changes (out of your scope)."
          print ""
          done_preamble = 1
        }
        next
      }
      fm == 1 && /^name:/         { print "name: " agent "-readonly"; next }
      fm == 1 && /^tools:/        { print "tools: Read, Grep, Glob, Bash"; next }
      fm == 1 && /^description:/  { print $0 " (READ-ONLY variant for Zaude read-only commands)"; next }
      { print }
    ' "$src" > "$dst"
    echo "${agent}-readonly.md" >> "$manifest"
    variants_generated=$((variants_generated + 1))
  done

  ok "v0.5 specialists: $installed installed + $variants_generated readonly variants"
  ok "  Manifest: $manifest"
}

if ask_yes_no "Install the 11 v0.5 VoltAgent specialists + their readonly variants now?" "y"; then
  install_voltagent_v05 || warn "v0.5 specialist install failed — re-run install.sh or follow the manual steps in docs/08-agents.md."
fi

# ---- done ----
cat <<EOF

${GREEN}${BOLD}Zaude installed.${RESET}

  Vault:         $VAULT_PATH
  Claude config: $CLAUDE_DIR
  Config file:   $HOME/.zaude/config.json
  First project: $PROJECT_SLUG (mapped to cwd basename "$PROJECT_CWD_BASE")

Next:
  1. Open a new Claude Code session in $PROJECT_CWD
  2. The initial system reminder should include "=== VAULT CONTEXT FOR $PROJECT_SLUG ==="
  3. Run /start to confirm Zaude is loaded
  4. Start shipping

${BOLD}Don't vibe code. Zaude code.${RESET}
EOF
