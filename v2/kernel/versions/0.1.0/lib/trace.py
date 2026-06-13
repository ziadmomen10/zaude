"""
trace.py — append-only event log (the ONE source of truth) + atomic projections.

trace.jsonl is append-only (O_APPEND + fsync). state.json is a DISPOSABLE projection
rebuilt by replaying the trace [R3]. Atomic writes via tmp + os.replace [D11]. A bare
.lock with PID+timestamp gives stale-lock recovery [codex#8,#12].
"""
import os
import json
import time
import errno
import tempfile

_PRIVATE_FILE = 0o600   # trace/log/lock are owner-only [A7]


class TraceCorrupt(Exception):
    pass


def _p(zaude_dir, name):
    return os.path.join(zaude_dir, name)


# ---------------------------------------------------------------- locking
def acquire_lock(zaude_dir, timeout=5.0, stale_after=30.0):
    """Best-effort exclusive lock via O_CREAT|O_EXCL carrying the owner pid. Recovers a
    stale lock (older than stale_after). Returns the lock path or raises TimeoutError."""
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
            # exists -> maybe stale
            try:
                age = time.time() - os.path.getmtime(lp)
                if age > stale_after:
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
    """Remove the lock ONLY if we still own it (PID match), so a process that reclaimed a
    stale lock can't have its lock deleted by the original owner. [A5, sec-M1]"""
    try:
        if lp and os.path.isfile(lp) and _lock_pid(lp) == os.getpid():
            os.remove(lp)
    except OSError:
        pass


# ---------------------------------------------------------------- trace
def append_row(zaude_dir, row):
    """Append one JSON row to trace.jsonl. Heals a torn tail BEFORE appending: a complete row
    always ends in '\\n', so any bytes after the last newline are an incomplete (never
    committed) write — we TRUNCATE them, then append. This is append-only for COMMITTED rows
    (only the never-finished partial is dropped), and it prevents a crash from fusing a partial
    with the next row into an interior-corrupt line that would brick the project.
    [A3, codex-C1, cr-C1]"""
    if "ts" not in row:
        row = dict(row, ts=time.time())
    line = json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
    p = _p(zaude_dir, "trace.jsonl")
    # NOTE: not O_APPEND — we may need to ftruncate a torn tail first.
    fd = os.open(p, os.O_CREAT | os.O_RDWR, _PRIVATE_FILE)
    try:
        size = os.fstat(fd).st_size
        if size:
            data = os.read(fd, size)             # small for the skeleton; Phase-2 scans the tail
            nl = data.rfind(b"\n")
            good = nl + 1                          # bytes up to & incl. the last newline
            if good != size:
                os.ftruncate(fd, good)            # drop the incomplete trailing write
            os.lseek(fd, good, os.SEEK_SET)
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return row


def read_trace(zaude_dir):
    """Return the list of trace rows. A corrupt LAST line (partial append) is quarantined
    and ignored; a corrupt INTERIOR line means tampering -> TraceCorrupt. [codex#13]"""
    p = _p(zaude_dir, "trace.jsonl")
    rows = []
    if not os.path.isfile(p):
        return rows
    with open(p, "r", encoding="utf-8") as f:
        lines = f.readlines()
    n = len(lines)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except Exception:
            if i == n - 1:
                break  # partial last line -> quarantine
            raise TraceCorrupt("corrupt trace line %d (interior)" % (i + 1))
    return rows


# ---------------------------------------------------------------- projection
def write_json_atomic(path, obj):
    """tmp + os.replace = atomic rename on Windows and POSIX. Uses a unique temp name
    (mkstemp, not pid) and cleans up on failure. [D11, M2, M5]"""
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
