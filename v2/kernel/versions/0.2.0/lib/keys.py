"""
keys.py — per-project HMAC key for the tamper-evident trace [B4].

The key lives OUTSIDE the repo tree (~/.zaude/keys/<hash>.key) so an agent constrained to
editing files inside the project cannot read it to forge a valid MAC. Loss of the key is not
fatal: the trace also carries a SHA-256 hash chain that detects naive append-forgery without
any key (keys.py just adds protection against a full-chain rewrite by someone who knows the
format). stdlib only.
"""
import os
import hashlib

_KEYS_DIR = os.path.join(os.path.expanduser("~"), ".zaude", "keys")


def _key_path(project_root):
    h = hashlib.sha256(os.path.normcase(project_root).encode("utf-8")).hexdigest()[:16]
    return os.path.join(_KEYS_DIR, h + ".key")


def get_or_create_key(project_root):
    """Return the 32-byte key for this project, creating it on first use (mode 0600)."""
    try:
        os.makedirs(_KEYS_DIR, exist_ok=True)
        kp = _key_path(project_root)
        if not os.path.isfile(kp):
            fd = os.open(kp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, os.urandom(32))
            finally:
                os.close(fd)
        with open(kp, "rb") as f:
            return f.read()
    except FileExistsError:
        with open(_key_path(project_root), "rb") as f:
            return f.read()
    except Exception:
        return None


def get_key(project_root):
    """Return the key if it exists, else None (read path — never creates)."""
    try:
        kp = _key_path(project_root)
        if os.path.isfile(kp):
            with open(kp, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None
