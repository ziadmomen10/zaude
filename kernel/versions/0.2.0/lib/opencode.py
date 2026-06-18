"""
opencode.py (v0.2.0) — GRACEFUL OpenCode availability + retry-memory for the THIRD review seat.

OpenCode (the most-starred OSS coding harness; provider-agnostic — it can drive Gemini / GPT /
local models) is a BEST-EFFORT, MODEL-DIVERSE review participant for high-risk (T3/T4) work —
NEVER a gate. It mirrors lib/codex.py exactly: a leaf lib (no trace/state import) that only answers
"is opencode usable right now, and if it was rate-limited, when to retry", records that honestly,
NEVER raises into the cycle, and NEVER blocks. Absence / auth-fail / quota / timeout / crash all
degrade to "unavailable / re-probe".

Differences from codex (codex co-plan):
  - OpenCode manages its OWN provider auth (no Zaude secrets token). READY is decided by the PRIMARY
    probe `opencode auth list` exit 0; an auth.json under the OpenCode data dir is only a HINT for
    the PRESENT_NOAUTH detail — file existence alone is NOT enough for READY. We NEVER read the auth
    file's CONTENTS.
  - classify_error WRAPS codex's pure classifier so OpenCode/provider-specific error vocabulary can
    evolve independently; an unmatched error degrades to UNKNOWN (never gates).
  - Independent retry state in .zaude/opencode.json — one seat's no-credit backoff NEVER touches the
    other's.

The DRIVER runs the review (`opencode run --model <provider/model> "<prompt>"`, with its own
timeout + output cap) and reports the verdict via `zaude review --opencode-verdict
pass|concerns|fail`. This module supplies only the availability signal + the retry memory. Every
subprocess has a hard timeout and its output is never logged. stdlib only.
"""
import os
import json
import time
import shutil
import subprocess

from . import codex as _codex   # reuse the PURE helpers (parse_retry_at, classify_error, due_now)

# ---- availability status (same stable strings as codex, so the ledger vocabulary is uniform) ----
MISSING = "missing"
PRESENT_NOAUTH = "present_noauth"
READY = "ready"

# ---- error reason codes (mirror codex's closed set) ----
RATE_LIMIT = _codex.RATE_LIMIT
QUOTA = _codex.QUOTA
AUTH = _codex.AUTH
TIMEOUT = _codex.TIMEOUT
UNKNOWN = _codex.UNKNOWN

_SIDE_FILE = "opencode.json"        # under .zaude/ — INDEPENDENT of codex.json
_SCHEMA = 1
_ENV_BIN = "ZAUDE_OPENCODE_BIN"


# ----------------------------- cli probes -----------------------------
def binary_path():
    return os.environ.get(_ENV_BIN) or shutil.which("opencode")


def _data_dirs():
    """Candidate OpenCode data dirs across platforms (auth.json lives here). Existence is only a
    HINT for the PRESENT_NOAUTH detail — never the basis for READY. Never raises."""
    home = os.path.expanduser("~")
    cands = [os.path.join(home, ".local", "share", "opencode")]
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        cands.append(os.path.join(xdg, "opencode"))
    for env in ("APPDATA", "LOCALAPPDATA"):
        v = os.environ.get(env)
        if v:
            cands.append(os.path.join(v, "opencode"))
    return cands


def _auth_file_hint():
    """True iff an auth.json exists + is non-trivial in a known data dir (HINT only — we never read
    its contents, only its size). Never raises."""
    for d in _data_dirs():
        try:
            p = os.path.join(d, "auth.json")
            if os.path.isfile(p) and os.path.getsize(p) > 2:   # bigger than "{}"
                return True
        except Exception:
            continue
    return False


def cli_version(timeout=5.0):
    """Best-effort `opencode --version` -> str|None. Swallows every error."""
    path = binary_path()
    if not path:
        return None
    try:
        p = subprocess.run([path, "--version"], capture_output=True, timeout=timeout)
        if p.returncode == 0:
            return (p.stdout or p.stderr or b"").decode("utf-8", "replace").strip()[:80] or None
    except Exception:
        return None
    return None


def cli_auth_ok(timeout=8.0):
    """SOLE readiness probe: `opencode auth list` exit 0 => a provider is configured. ONLY this
    command decides READY (codex review HIGH: no `auth status` fallback — its looser semantics /
    Windows shimming could false-READY). Errs toward False (safe: we then report PRESENT_NOAUTH and
    merely nudge, never claim readiness). Output is never logged. Never raises."""
    path = binary_path()
    if not path:
        return False
    try:
        p = subprocess.run([path, "auth", "list"], capture_output=True, timeout=timeout)
        return p.returncode == 0
    except Exception:
        return False


def probe(timeout=8.0):
    """Three-valued availability. NEVER raises. READY requires `opencode auth list` exit 0 (PRIMARY)
    — an auth.json hint alone is NOT enough (file existence != provider configured). Returns a dict
    written to the side file / ledger."""
    now = time.time()
    try:
        if not binary_path():
            return {"status": MISSING, "version": None, "auth_source": None,
                    "checked_at": now, "detail": "opencode not found on PATH"}
        version = cli_version(timeout=timeout)
        if cli_auth_ok(timeout=timeout):
            return {"status": READY, "version": version, "auth_source": "cli_auth",
                    "checked_at": now, "detail": "provider configured (opencode auth list)"}
        if _auth_file_hint():
            return {"status": PRESENT_NOAUTH, "version": version, "auth_source": None,
                    "checked_at": now, "detail": "auth.json present but `opencode auth list` not OK"}
        return {"status": PRESENT_NOAUTH, "version": version, "auth_source": None,
                "checked_at": now, "detail": "installed but no provider configured"}
    except Exception as e:
        return {"status": MISSING, "version": None, "auth_source": None,
                "checked_at": now, "detail": "probe error: %s" % str(e)[:60]}


# ----------------------------- error classification (wrap codex's pure classifier) -----------------------------
def parse_retry_at(s):
    return _codex.parse_retry_at(s)


def classify_error(exit_code, stderr_text="", stdout_text="", now=None):
    """Delegate to codex's pure classifier today; wrapping it means OpenCode/provider-specific error
    vocabulary can be added here later WITHOUT making Codex's vocabulary authoritative. An unmatched
    error degrades to UNKNOWN (never gates). [codex co-plan]"""
    return _codex.classify_error(exit_code, stderr_text, stdout_text, now=now)


# ----------------------------- retry memory (INDEPENDENT side file) -----------------------------
def _path(zaude_dir):
    return os.path.join(zaude_dir, _SIDE_FILE)


def read_status(zaude_dir):
    """Read .zaude/opencode.json (operational state — NOT signed). Default skeleton on any error."""
    try:
        with open(_path(zaude_dir), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {"schema": _SCHEMA, "last_probe": None,
            "retry": {"blocked": False, "reason": None, "retry_at": None, "noted_at": None}}


def write_status(zaude_dir, obj):
    try:
        from . import trace as _trace
        _trace.write_json_atomic(_path(zaude_dir), obj)
    except Exception:
        pass


def note_no_credit(zaude_dir, reason, retry_at):
    d = read_status(zaude_dir)
    d["retry"] = {"blocked": True, "reason": reason, "retry_at": retry_at, "noted_at": time.time()}
    write_status(zaude_dir, d)
    return d


def clear_retry(zaude_dir):
    d = read_status(zaude_dir)
    d["retry"] = {"blocked": False, "reason": None, "retry_at": None, "noted_at": time.time()}
    write_status(zaude_dir, d)
    return d


def due_now(status, now=None):
    return _codex.due_now(status, now)
