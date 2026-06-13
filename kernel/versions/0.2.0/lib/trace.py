"""
trace.py (v0.2.0) — append-only, TAMPER-EVIDENT event log + atomic projections.

Each row carries `seq` + `prev` (sha256 of the previous row's canonical form) + `mac`
(HMAC-SHA256 over the canonical row, keyed by a per-project key stored OUTSIDE the repo).
- The SHA-256 CHAIN detects naive append-forgery with NO key (a hand-appended row won't carry
  the right `prev`).  [defeats the v0.1.0 "append one line to fake Designed" attack at the
  integrity layer, in addition to the state-machine's validating replay]
- The HMAC additionally defeats a full-chain rewrite by someone who knows the format but can't
  read the key (an agent confined to repo files).
Heals a torn tail before append; atomic state writes; PID-owned lock. stdlib only.
"""
import os
import json
import time
import errno
import hmac
import hashlib
import tempfile

from . import keys as _keys

_PRIVATE_FILE = 0o600
GENESIS = "GENESIS"


class TraceCorrupt(Exception):
    """Unparseable interior line — structural damage."""


class TraceForged(Exception):
    """Chain/MAC mismatch — the log was tampered with."""


def _p(zaude_dir, name):
    return os.path.join(zaude_dir, name)


def _canonical(row):
    """Deterministic serialization of a row EXCLUDING its own mac."""
    r = {k: v for k, v in row.items() if k != "mac"}
    return json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _row_hash(row):
    return hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- locking
def acquire_lock(zaude_dir, timeout=5.0, stale_after=30.0):
    lp = _p(zaude_dir, ".lock")
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _PRIVATE_FILE)
            os.write(fd, ("%d\n%f\n" % (os.getpid(), time.time())).encode("utf-8"))
            os.close(fd)
            return lp
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            try:
                if time.time() - os.path.getmtime(lp) > stale_after:
                    os.remove(lp)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                raise TimeoutError("could not acquire .zaude/.lock")
            time.sleep(0.05)


def _lock_pid(lp):
    try:
        with open(lp, "r", encoding="utf-8") as f:
            return int(f.readline().strip())
    except Exception:
        return None


def release_lock(lp):
    try:
        if lp and os.path.isfile(lp) and _lock_pid(lp) == os.getpid():
            os.remove(lp)
    except OSError:
        pass


# ---------------------------------------------------------------- trace
def _read_lines(zaude_dir):
    p = _p(zaude_dir, "trace.jsonl")
    if not os.path.isfile(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        return f.readlines()


def _parse(lines):
    """Parse JSONL; quarantine a partial LAST line; raise on interior corruption."""
    rows = []
    n = len(lines)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except Exception:
            if i == n - 1:
                break
            raise TraceCorrupt("corrupt trace line %d (interior)" % (i + 1))
    return rows


def read_trace(zaude_dir, project_root=None, verify=True):
    """Return rows. With verify=True, validate the hash chain (always) and the HMAC (if the
    key is present), raising TraceForged on any mismatch."""
    rows = _parse(_read_lines(zaude_dir))
    if not verify:
        return rows
    key = _keys.get_key(project_root) if project_root else None
    # If the trace already carries MACs but the key is gone, we CANNOT verify integrity —
    # fail closed rather than silently downgrade to chain-only. The key lives outside the repo
    # (~/.zaude/keys), so a repo-writer can't delete it; key-None here means real loss. [codex-CRIT]
    if key is None and any("mac" in r for r in rows):
        raise TraceForged("integrity key missing but trace carries MACs — cannot verify")
    prev = GENESIS
    for i, row in enumerate(rows):
        if row.get("seq") != i:
            raise TraceForged("seq mismatch at row %d (got %r)" % (i, row.get("seq")))
        if row.get("prev") != prev:
            raise TraceForged("broken hash chain at row %d" % i)
        if key is not None:
            expect = hmac.new(key, _canonical(row).encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expect, row.get("mac", "")):
                raise TraceForged("bad MAC at row %d" % i)
        prev = _row_hash(row)
    return rows


def append_row(zaude_dir, row, project_root):
    """Append one chained+MAC'd row. Reads+verifies the existing chain first so we never
    extend a tampered log. Heals a torn tail (truncates an incomplete trailing write)."""
    existing = read_trace(zaude_dir, project_root, verify=True)
    seq = len(existing)
    prev = _row_hash(existing[-1]) if existing else GENESIS

    base = {k: v for k, v in row.items() if k not in ("seq", "prev", "mac")}
    base.setdefault("ts", time.time())
    base["seq"] = seq
    base["prev"] = prev
    key = _keys.get_or_create_key(project_root)
    if key is not None:
        base["mac"] = hmac.new(key, _canonical(base).encode("utf-8"), hashlib.sha256).hexdigest()

    line = json.dumps(base, separators=(",", ":"), ensure_ascii=False) + "\n"
    p = _p(zaude_dir, "trace.jsonl")
    fd = os.open(p, os.O_CREAT | os.O_RDWR, _PRIVATE_FILE)
    try:
        size = os.fstat(fd).st_size
        if size:
            data = os.read(fd, size)
            good = data.rfind(b"\n") + 1
            if good != size:
                os.ftruncate(fd, good)
            os.lseek(fd, good, os.SEEK_SET)
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return base


# ---------------------------------------------------------------- projection
def write_json_atomic(path, obj):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def write_state(zaude_dir, state_obj):
    write_json_atomic(_p(zaude_dir, "state.json"), state_obj)


def read_state(zaude_dir):
    try:
        with open(_p(zaude_dir, "state.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
