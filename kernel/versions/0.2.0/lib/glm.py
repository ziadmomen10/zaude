"""
glm.py (v0.2.0) — GRACEFUL GLM (Zhipu / z.ai) availability + retry-memory for the FIFTH review seat.

GLM (Zhipu AI, served via z.ai's Anthropic-compatible endpoint) is a BEST-EFFORT, MODEL-DIVERSE
review participant for high-risk (T3/T4) work — NEVER a gate. z.ai ships NO standalone GLM binary; the
GLM Coding Plan is consumed through an existing agent harness pointed at https://api.z.ai/api/anthropic.
Here the RUNNER is Claude Code itself, pointed at z.ai via an isolated `claude-glm` wrapper
(ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN + ANTHROPIC_MODEL=glm-*), so the SEAT's MODEL is GLM even
though the harness is claude-code — the uncorrelated-error benefit comes from the MODEL, not the
harness. This mirrors lib/codex.py's TOKEN model (not kimi.py's creds-dir model).

A leaf lib (no trace/state import) that only answers "is GLM usable right now (a z.ai token + a runner
present), and if it was rate-limited, when to retry", records that honestly, NEVER raises into the
cycle, and NEVER blocks. Absence / auth-fail / quota / timeout / crash all degrade to "unavailable".

Token contract mirrors codex/pm_github: ~/.zaude/secrets/zai (a real file, not a symlink, resolving
under the secrets dir) OR the ZAI_API_KEY / ZAUDE_GLM_TOKEN env var. The token value is NEVER logged,
echoed, or written to any artifact/side-file — only the LABEL (token_file|env). The runner binary is
`claude` (override with ZAUDE_GLM_BIN to point at the `claude-glm` wrapper). classify_error /
parse_retry_at / due_now are reused from codex so the error vocabulary stays uniform. stdlib only.

The DRIVER runs the review (`claude-glm -p "<prompt>"` — claude-code headless against z.ai) and reports
the verdict via `zaude review --glm-verdict pass|concerns|fail`. This module supplies only the
availability signal + the retry memory.
"""
import os
import time
import shutil
import json
import subprocess

from . import codex as _codex   # reuse the PURE helpers (parse_retry_at, classify_error, due_now)

# ---- availability status (same stable strings as codex/opencode/kimi, so the ledger is uniform) ----
MISSING = "missing"                 # no runner (claude) on PATH -> GLM cannot be invoked at all
PRESENT_NOAUTH = "present_noauth"   # runner present but no z.ai token
READY = "ready"                     # runner present AND a z.ai token is configured

# ---- error reason codes (mirror codex's closed set) ----
RATE_LIMIT = _codex.RATE_LIMIT
QUOTA = _codex.QUOTA
AUTH = _codex.AUTH
TIMEOUT = _codex.TIMEOUT
UNKNOWN = _codex.UNKNOWN

_SECRET_DIR = os.path.join(os.path.expanduser("~"), ".zaude", "secrets")
_SECRET_FILE = os.path.join(_SECRET_DIR, "zai")
_ENV_VARS = ("ZAI_API_KEY", "ZAUDE_GLM_TOKEN")

_SIDE_FILE = "glm.json"             # under .zaude/ — INDEPENDENT of codex/opencode/kimi side files
_SCHEMA = 1
_ENV_BIN = "ZAUDE_GLM_BIN"          # override the runner (defaults to `claude`)


# ----------------------------- token (hardened, mirrors codex._secret_ok) -----------------------------
def _secret_ok():
    """A real file (not a symlink) resolving under the secrets dir. Mirrors codex/pm_github."""
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
    """Return (token, source_label) WITHOUT ever logging the token. Priority: env, then the hardened
    file. (None, None) when neither is present. Never raises."""
    try:
        for var in _ENV_VARS:
            env = os.environ.get(var)
            if env and env.strip():
                return env.strip(), "env"
        if _secret_ok():
            with open(_SECRET_FILE, "r", encoding="utf-8") as f:
                t = f.read(8192).strip()
            if t:
                return t, "token_file"
    except Exception:
        pass
    return None, None


def have_token():
    return token_source()[0] is not None


def token_misconfigured():
    """True only when a zai token FILE exists but is unsafe (symlink / wrong location). Used by /doctor
    to flag a real misconfiguration (vs. mere absence, which is fine)."""
    try:
        return (os.path.exists(_SECRET_FILE) or os.path.islink(_SECRET_FILE)) and not _secret_ok()
    except Exception:
        return False


# ----------------------------- cli probes -----------------------------
def binary_path():
    """The RUNNER for GLM — claude-code pointed at z.ai. Override with ZAUDE_GLM_BIN (e.g. a
    `claude-glm` wrapper). Falls back to `claude` on PATH."""
    return os.environ.get(_ENV_BIN) or shutil.which("claude")


def cli_version(timeout=5.0):
    """Best-effort `<runner> --version` -> str|None. Swallows every error."""
    path = binary_path()
    if not path:
        return None
    try:
        p = subprocess.run([path, "--version"], capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        if p.returncode == 0:
            return (p.stdout or p.stderr or b"").decode("utf-8", "replace").strip()[:80] or None
    except Exception:
        return None
    return None


def probe(timeout=8.0):
    """Three-valued availability. NEVER raises. READY requires BOTH a runner (claude/claude-glm on
    PATH) AND a z.ai token (env or hardened file). A present runner with no token is PRESENT_NOAUTH; no
    runner at all is MISSING. Returns a dict written to the side file / ledger (LABELS only — never the
    token value)."""
    now = time.time()
    try:
        if not binary_path():
            return {"status": MISSING, "version": None, "auth_source": None,
                    "checked_at": now, "detail": "no GLM runner (claude/claude-glm) on PATH"}
        version = cli_version(timeout=timeout)
        tok, src = token_source()
        if tok is not None:
            return {"status": READY, "version": version, "auth_source": src,
                    "checked_at": now, "detail": "z.ai token present (%s)" % src}
        return {"status": PRESENT_NOAUTH, "version": version, "auth_source": None,
                "checked_at": now, "detail": "runner present but no z.ai token"}
    except Exception as e:
        return {"status": MISSING, "version": None, "auth_source": None,
                "checked_at": now, "detail": "probe error: %s" % str(e)[:60]}


# ----------------------------- error classification (reuse codex's pure classifier) -----------------------------
def parse_retry_at(s):
    return _codex.parse_retry_at(s)


def classify_error(exit_code, stderr_text="", stdout_text="", now=None):
    """Delegate to codex's pure classifier today; wrapping it means GLM/z.ai-specific error vocabulary
    can be added here later WITHOUT making Codex's vocabulary authoritative. Unmatched -> UNKNOWN."""
    return _codex.classify_error(exit_code, stderr_text, stdout_text, now=now)


# ----------------------------- retry memory (INDEPENDENT side file) -----------------------------
def _path(zaude_dir):
    return os.path.join(zaude_dir, _SIDE_FILE)


def read_status(zaude_dir):
    """Read .zaude/glm.json (operational state — NOT signed). Default skeleton on any error."""
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
