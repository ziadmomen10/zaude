"""
dist.py — package Zaude into a portable distribution + the bootstrap install scripts, so it can be
set up on a fresh PC. `package(out_dir)` assembles a CLEAN dist (bin + policy + kernel + scripts)
with NO secrets / generated / restore-points / project state, and refuses if a token string leaks
in. The install scripts lay that dist down into ~/.zaude on the target machine. stdlib only.
"""
import os
import re
import shutil

HOME = os.path.expanduser("~")
ZROOT = os.path.join(HOME, ".zaude")
# never ship these
_EXCLUDE_TOP = {"secrets", "generated", "restore-points", "installed.json", "dist", ".src", "disabled"}
_TOKEN_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")

INSTALL_PS1 = r"""# Zaude bootstrap installer (Windows / PowerShell 5.1-safe)
param([switch]$WireClaude)
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$dst = Join-Path $HOME ".zaude"
$py = $null
foreach ($c in @("python","python3")) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) { Write-Error "Python 3 is required but was not found on PATH."; exit 1 }
Write-Host "Installing Zaude to $dst ..."
foreach ($sub in @("bin","policy","kernel")) {
  $s = Join-Path $src $sub
  if (Test-Path $s) {
    $d = Join-Path $dst $sub
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Copy-Item -Recurse -Force (Join-Path $s "*") $d
  }
}
& $py (Join-Path $dst "bin\zaude.py") gen
Write-Host ""
Write-Host "Zaude installed (kernel $(Get-Content (Join-Path $dst 'kernel\CURRENT')))."
if ($WireClaude) {
  & $py (Join-Path $dst "bin\zaude.py") install --yes
} else {
  Write-Host "To wire the /z* slash commands + the fail-open hook into ~/.claude, run:"
  Write-Host "  python `"$dst\bin\zaude.py`" install --yes"
}
Write-Host "Note: copy your GitHub PAT to ~/.zaude/secrets/github-pat to enable the PM board."
"""

INSTALL_SH = r"""#!/usr/bin/env bash
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
"""

README = """# Zaude — portable engineering framework

Deterministic Claude-Code workflow kernel: a state machine + tamper-evident trace + risk-scaled
gates, a GitHub Projects PM layer, and a generated slash-command interface.

## Install on a fresh PC
```bash
git clone https://github.com/ziadmomen10/zaude-framework "$HOME/.zaude-src"
bash "$HOME/.zaude-src/install.sh"            # or:  powershell -File "$HOME\\.zaude-src\\install.ps1"
```
Then (optional) wire the slash commands + hook into your Claude Code config:
```bash
python "$HOME/.zaude/bin/zaude.py" install --yes
```
Add your GitHub PAT to `~/.zaude/secrets/github-pat` (never committed) to enable the PM board.

## Update
```bash
python "$HOME/.zaude/bin/zaude.py" update --source https://github.com/ziadmomen10/zaude-framework
```
Pulls new kernel versions, bumps CURRENT, regenerates, and re-wires (if installed). Reversible via
`~/.zaude/restore-points/` and `python ~/.zaude/bin/zaude.py uninstall`.

## Safety
- The PAT lives ONLY at `~/.zaude/secrets/` — never in this repo, the trace, or any pushed file.
- The PreToolUse hook FAILS OPEN: projects without `.zaude/` are untouched; onboard in shadow mode first.
"""

GITIGNORE = "secrets/\ngenerated/\nrestore-points/\ninstalled.json\n.src/\n__pycache__/\n*.pyc\ndisabled\n"


def _rmtree_force(path):
    """rmtree that clears the read-only attribute (git objects are read-only on Windows)."""
    import stat

    def _onerror(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    try:
        shutil.rmtree(path, onexc=_onerror)          # py3.12+
    except TypeError:
        shutil.rmtree(path, onerror=_onerror)        # older


def _copy_clean(src_root, dst_root):
    """Copy a subtree excluding __pycache__/*.pyc/.lock and tmp files."""
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        rel = os.path.relpath(dirpath, src_root)
        out = os.path.join(dst_root, rel) if rel != "." else dst_root
        os.makedirs(out, exist_ok=True)
        for fn in filenames:
            if fn.endswith(".pyc") or fn == ".lock" or ".tmp." in fn:
                continue
            shutil.copyfile(os.path.join(dirpath, fn), os.path.join(out, fn))


def package(out_dir):
    """Assemble a clean, portable dist at out_dir. Returns a summary. Raises if a token leaks."""
    if os.path.abspath(out_dir).startswith(os.path.abspath(ZROOT) + os.sep) or os.path.abspath(out_dir) == os.path.abspath(ZROOT):
        raise ValueError("out_dir must be OUTSIDE ~/.zaude (don't ship secrets)")
    if os.path.isdir(out_dir):
        _rmtree_force(out_dir)
    os.makedirs(out_dir)
    for sub in ("bin", "policy", "kernel"):
        s = os.path.join(ZROOT, sub)
        if os.path.isdir(s):
            _copy_clean(s, os.path.join(out_dir, sub))
    with open(os.path.join(out_dir, "install.ps1"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(INSTALL_PS1)
    with open(os.path.join(out_dir, "install.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write(INSTALL_SH)
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(README)
    with open(os.path.join(out_dir, ".gitignore"), "w", encoding="utf-8", newline="\n") as f:
        f.write(GITIGNORE)
    # SECURITY: refuse to ship if any token-like string or a secrets dir slipped in
    leaks = []
    for dp, dn, fns in os.walk(out_dir):
        if "secrets" in dp.split(os.sep):
            leaks.append(os.path.relpath(dp, out_dir))
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                if _TOKEN_RE.search(open(p, "r", encoding="utf-8", errors="ignore").read()):
                    leaks.append(os.path.relpath(p, out_dir))
            except Exception:
                pass
    if leaks:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise ValueError("ABORT: secret/token leaked into dist: %s" % leaks[:5])
    n = sum(len(fns) for _, _, fns in os.walk(out_dir))
    return {"out_dir": out_dir, "files": n}
