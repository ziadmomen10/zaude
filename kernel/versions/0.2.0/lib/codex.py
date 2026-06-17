"""
codex.py (v0.2.0) — GRACEFUL codex availability + retry-memory for the review panel [L13].

Codex is a BEST-EFFORT review participant for high-risk (T3/T4) work — NEVER a gate. This leaf
lib (no trace/state import, like keys.py) only answers "is codex usable right now, and if it was
rate-limited, when should we try again" and records that honestly. It NEVER raises into the cycle
and NEVER blocks: every subprocess is wrapped, every failure degrades to "unavailable / re-probe".

The kernel does NOT construct the review prompt (it has no diff in-context) — the DRIVER runs
codex and reports the verdict via `zaude review --codex-verdict`. This module supplies the
availability signal (for the honest record + the soft "you have codex, use it" nudge) and the
no-credit retry memory (so an out-of-credit codex is auto-retried when its reset time passes).

Token contract mirrors pm_github._secret_ok: ~/.zaude/secrets/codex (real file, not a symlink,
resolving under the secrets dir) OR the ZAUDE_CODEX_TOKEN env var. The token value is NEVER
logged, echoed, or written to any artifact/side-file — only the LABEL (token_file|env|cli_login).
stdlib only.
"""
import os
import re
import json
import time
import shutil
import subprocess

# ---- availability status (stable strings — written to the ledger + side file) ----
MISSING = "missing"                 # `codex` binary not on PATH
PRESENT_NOAUTH = "present_noauth"   # installed but no token AND not logged in
READY = "ready"                     # installed AND (token present OR `codex` reports logged-in)

# ---- error reason codes (closed set) ----
RATE_LIMIT = "rate_limit"
QUOTA = "quota"                     # out of credit
AUTH = "auth"                       # token rejected / expired
TIMEOUT = "timeout"
UNKNOWN = "unknown"

_SECRET_DIR = os.path.join(os.path.expanduser("~"), ".zaude", "secrets")
_SECRET_FILE = os.path.join(_SECRET_DIR, "codex")
_ENV_VAR = "ZAUDE_CODEX_TOKEN"

_SIDE_FILE = "codex.json"           # under .zaude/
_SCHEMA = 1


# ----------------------------- token (hardened) -----------------------------
def _secret_ok():
    """Mirror pm_github._secret_ok: a real file (not a symlink) resolving under the secrets dir."""
    try:
        if not os.path.isfile(_SECRET_FILE) or os.path.islink(_SECRET_FILE):
            return False
        if os.path.normcase(os.path.dirname(os.path.realpath(_SECRET_FILE))) != \
           os.path.normcase(os.path.realpath(_SECRET_DIR)):
            return False
        return True
    except Exception:
        return False


def token_source():
    """Return (token, source_label) WITHOUT ever logging the token. Priority: env, then the
    hardened file. (None, None) when neither is present. Never raises."""
    try:
        env = os.environ.get(_ENV_VAR)
        if env and env.strip():
            return env.strip(), "env"
        if _secret_ok():
            with open(_SECRET_FILE, "r", encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t, "token_file"
    except Exception:
        pass
    return None, None


def have_token():
    return token_source()[0] is not None


def token_misconfigured():
    """True only when a codex token FILE exists but is unsafe (symlink / wrong location). Used by
    /doctor to flag a real misconfiguration (vs. mere absence, which is fine)."""
    try:
        return (os.path.exists(_SECRET_FILE) or os.path.islink(_SECRET_FILE)) and not _secret_ok()
    except Exception:
        return False


# ----------------------------- cli probes -----------------------------
def binary_path():
    return os.environ.get("ZAUDE_CODEX_BIN") or shutil.which("codex")


def cli_version(timeout=5.0):
    """Best-effort `codex --version` -> str|None. Swallows every error."""
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
    """Best-effort 'is codex logged in?' probe. The exact subcommand is codex-CLI-specific; we try
    a cheap non-interactive status probe and treat exit 0 as logged-in. Errs toward False (safe:
    we then report PRESENT_NOAUTH and merely nudge, never claim readiness). Never raises."""
    path = binary_path()
    if not path:
        return False
    for args in (["login", "status"], ["whoami"], ["auth", "status"]):
        try:
            p = subprocess.run([path] + args, capture_output=True, timeout=timeout)
            if p.returncode == 0:
                return True
        except Exception:
            continue
    return False


def probe(timeout=8.0):
    """Three-valued availability. NEVER raises (top-level guard honors the module contract — a
    failure anywhere degrades to MISSING, never propagates into the cycle). Returns a dict written
    to the side file/ledger (LABELS only — never the token value)."""
    now = time.time()
    try:
        if not binary_path():
            return {"status": MISSING, "version": None, "auth_source": None,
                    "checked_at": now, "detail": "codex not found on PATH"}
        version = cli_version()
        tok, src = token_source()
        if tok is not None:
            return {"status": READY, "version": version, "auth_source": src,
                    "checked_at": now, "detail": "token present (%s)" % src}
        if cli_auth_ok(timeout=timeout):
            return {"status": READY, "version": version, "auth_source": "cli_login",
                    "checked_at": now, "detail": "logged in via codex cli"}
        return {"status": PRESENT_NOAUTH, "version": version, "auth_source": None,
                "checked_at": now, "detail": "installed but not logged in / no token"}
    except Exception as e:
        return {"status": MISSING, "version": None, "auth_source": None,
                "checked_at": now, "detail": "probe error: %s" % str(e)[:60]}


def parse_retry_at(s):
    """Parse a driver-supplied retry time (epoch seconds OR ISO-8601) -> float|None. Never raises."""
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ----------------------------- error classification -----------------------------
_RETRY_AFTER_RE = re.compile(r"retry[\s\-]?after[:\s]+(\d+)\s*(s|sec|second|m|min|minute|h|hour)?",
                             re.IGNORECASE)
_RESET_EPOCH_RE = re.compile(r"(?:reset|retry)[^0-9]{0,20}(1[6-9]\d{8})")   # a 10-digit epoch
_QUOTA_RE = re.compile(r"(quota|out of credit|insufficient.*credit|billing|payment required|"
                       r"hard limit|usage limit)", re.IGNORECASE)
_RATE_RE = re.compile(r"(rate.?limit|too many requests|429|slow down)", re.IGNORECASE)
_AUTH_RE = re.compile(r"(unauthorized|401|invalid.*(token|key|credential)|not logged in|"
                      r"authentication)", re.IGNORECASE)


def _retry_at_from(text, now):
    """Best-effort reset-time extraction. Returns epoch float or None (None => re-probe each time,
    never a hard wait)."""
    m = _RESET_EPOCH_RE.search(text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    m = _RETRY_AFTER_RE.search(text)
    if m:
        try:
            n = int(m.group(1))
            unit = (m.group(2) or "s").lower()
            mult = 1
            if unit.startswith("m"):
                mult = 60
            elif unit.startswith("h"):
                mult = 3600
            return now + n * mult
        except Exception:
            pass
    return None


def classify_error(exit_code, stderr_text="", stdout_text="", now=None):
    """Map a failed codex invocation to {reason, retry_at, message}. Best-effort; on no match ->
    UNKNOWN/None (harmless: re-probe next time). Never raises."""
    if now is None:
        now = time.time()
    text = ("%s\n%s" % (stderr_text or "", stdout_text or ""))[:4000]
    if _QUOTA_RE.search(text):
        return {"reason": QUOTA, "retry_at": _retry_at_from(text, now), "message": "out of credit"}
    if _RATE_RE.search(text):
        return {"reason": RATE_LIMIT, "retry_at": _retry_at_from(text, now), "message": "rate limited"}
    if _AUTH_RE.search(text):
        return {"reason": AUTH, "retry_at": None, "message": "auth rejected — re-login"}
    return {"reason": UNKNOWN, "retry_at": None, "message": ("codex exit %s" % exit_code)}


# ----------------------------- retry memory (side file) -----------------------------
def _path(zaude_dir):
    return os.path.join(zaude_dir, _SIDE_FILE)


def read_status(zaude_dir):
    """Read .zaude/codex.json (operational state — NOT signed). Returns a default skeleton on any
    error. Never raises."""
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
    """Atomic write via the same primitive the kernel uses for state.json. Best-effort."""
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
    """Should we attempt codex now? True if not blocked, or no retry_at, or now >= retry_at.
    (User intent: re-invoke when now>=reset; if no reset time known, re-probe each time.)"""
    if now is None:
        now = time.time()
    retry = (status or {}).get("retry") or {}
    if not retry.get("blocked"):
        return True
    ra = retry.get("retry_at")
    if ra is None:
        return True
    try:
        return now >= float(ra)
    except Exception:
        return True
