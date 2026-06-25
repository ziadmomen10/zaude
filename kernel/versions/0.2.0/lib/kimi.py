"""
kimi.py (v0.2.0) — GRACEFUL Kimi availability + retry-memory for the FOURTH review seat.

Kimi (Moonshot, model `kimi-for-coding`) is a BEST-EFFORT, MODEL-DIVERSE review participant for
high-risk (T3/T4) work — NEVER a gate. It mirrors lib/opencode.py exactly: a leaf lib (no trace/state
import) that only answers "is kimi usable right now, and if it was rate-limited, when to retry",
records that honestly, NEVER raises into the cycle, and NEVER blocks. Absence / auth-fail / quota /
timeout / crash all degrade to "unavailable / re-probe".

Differences from opencode (auth model):
  - Kimi authenticates via OAuth (`kimi login`); credentials live UNDER ~/.kimi/credentials/ (e.g.
    kimi-code.json). Unlike OpenCode there is NO cheap non-interactive `auth list` probe (the only
    subcommands are login/logout/term/acp), so READY is decided by the PRESENCE of a non-trivial
    credentials file — we NEVER read its CONTENTS, only that it exists and is bigger than "{}". A
    stale credential simply surfaces as a driver-side error later (recorded as no_credit/unavailable),
    which is the same honest degradation every seat already has.
  - classify_error WRAPS codex's pure classifier so Kimi/provider-specific error vocabulary can evolve
    independently; an unmatched error degrades to UNKNOWN (never gates).
  - Independent retry state in .zaude/kimi.json — one seat's no-credit backoff NEVER touches another's.

The DRIVER runs the review (`kimi --quiet --afk --input-format text < prompt` and reports the verdict
via `zaude review --kimi-verdict pass|concerns|fail`). This module supplies only the availability
signal + the retry memory. Every subprocess has a hard timeout and its output is never logged.
stdlib only.
"""
import os
import json
import time
import shutil
import subprocess

from . import codex as _codex   # reuse the PURE helpers (parse_retry_at, classify_error, due_now)

# ---- availability status (same stable strings as codex/opencode, so the ledger vocabulary is uniform) ----
MISSING = "missing"
PRESENT_NOAUTH = "present_noauth"
READY = "ready"

# ---- error reason codes (mirror codex's closed set) ----
RATE_LIMIT = _codex.RATE_LIMIT
QUOTA = _codex.QUOTA
AUTH = _codex.AUTH
TIMEOUT = _codex.TIMEOUT
UNKNOWN = _codex.UNKNOWN

_SIDE_FILE = "kimi.json"          # under .zaude/ — INDEPENDENT of codex.json / opencode.json
_SCHEMA = 1
_ENV_BIN = "ZAUDE_KIMI_BIN"
_CREDS_DIR = os.path.join(os.path.expanduser("~"), ".kimi", "credentials")


# ----------------------------- cli probes -----------------------------
def binary_path():
    return os.environ.get(_ENV_BIN) or shutil.which("kimi")


def _creds_present():
    """True iff a non-trivial credentials file exists under ~/.kimi/credentials/ (HINT of an OAuth
    login). We NEVER read its contents — only that some file there is bigger than "{}". Never raises."""
    try:
        if not os.path.isdir(_CREDS_DIR):
            return False
        for name in os.listdir(_CREDS_DIR):
            p = os.path.join(_CREDS_DIR, name)
            if os.path.isfile(p) and os.path.getsize(p) > 2:
                return True
    except Exception:
        pass
    return False


def cli_version(timeout=5.0):
    """Best-effort `kimi --version` -> str|None. Swallows every error."""
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


def probe(timeout=8.0):
    """Three-valued availability. NEVER raises. READY requires the `kimi` binary AND a non-trivial
    credential file under ~/.kimi/credentials/ (an OAuth login). There is no cheap non-interactive
    auth-status subcommand, so credential-file presence is the readiness signal (we never read its
    contents); a stale credential degrades to a driver-side error later, recorded honestly. Returns a
    dict written to the side file / ledger (LABELS only — never any token value)."""
    now = time.time()
    try:
        if not binary_path():
            return {"status": MISSING, "version": None, "auth_source": None,
                    "checked_at": now, "detail": "kimi not found on PATH"}
        version = cli_version(timeout=timeout)
        if _creds_present():
            return {"status": READY, "version": version, "auth_source": "oauth_creds",
                    "checked_at": now, "detail": "logged in (~/.kimi/credentials present)"}
        return {"status": PRESENT_NOAUTH, "version": version, "auth_source": None,
                "checked_at": now, "detail": "installed but not logged in (run `kimi login`)"}
    except Exception as e:
        return {"status": MISSING, "version": None, "auth_source": None,
                "checked_at": now, "detail": "probe error: %s" % str(e)[:60]}


# ----------------------------- error classification (wrap codex's pure classifier) -----------------------------
def parse_retry_at(s):
    return _codex.parse_retry_at(s)


def classify_error(exit_code, stderr_text="", stdout_text="", now=None):
    """Delegate to codex's pure classifier today; wrapping it means Kimi/provider-specific error
    vocabulary can be added here later WITHOUT making Codex's vocabulary authoritative. An unmatched
    error degrades to UNKNOWN (never gates)."""
    return _codex.classify_error(exit_code, stderr_text, stdout_text, now=now)


# ----------------------------- retry memory (INDEPENDENT side file) -----------------------------
def _path(zaude_dir):
    return os.path.join(zaude_dir, _SIDE_FILE)


def read_status(zaude_dir):
    """Read .zaude/kimi.json (operational state — NOT signed). Default skeleton on any error."""
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
