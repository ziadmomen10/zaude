#!/usr/bin/env bash
# Zaude bootstrap installer (bash / git-bash / macOS / Linux)
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="$HOME/.zaude"
PY="$(command -v python3 || command -v python || true)"
[ -z "$PY" ] && { echo "Python 3 is required but was not found on PATH."; exit 1; }
echo "Installing Zaude to $DST ..."
for sub in bin policy kernel; do
  if [ -d "$SRC/$sub" ]; then mkdir -p "$DST/$sub"; cp -rf "$SRC/$sub/." "$DST/$sub/"; fi
done
"$PY" "$DST/bin/zaude.py" gen
echo ""
echo "Zaude installed (kernel $(cat "$DST/kernel/CURRENT"))."
if [ "${1:-}" = "--wire-claude" ]; then
  "$PY" "$DST/bin/zaude.py" install --yes
else
  echo "To wire the /z* slash commands + the fail-open hook into ~/.claude, run:"
  echo "  $PY \"$DST/bin/zaude.py\" install --yes"
fi
echo "Note: copy your GitHub PAT to ~/.zaude/secrets/github-pat to enable the PM board."
