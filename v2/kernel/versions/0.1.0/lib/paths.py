"""
paths.py — project resolution + the FAIL-OPEN safety probe.

This is the single most safety-critical file in the kernel. The Zaude hooks run on
EVERY project on this machine (including the 21 not onboarded). The contract:

  A dir is "onboarded" ONLY if <root>/.zaude/project.json validates AND its canonical
  project_root == the resolved repo root. Anything else -> returns None -> the caller
  fails OPEN (does nothing, exits 0). [codex#2,#3,#4]

No third-party imports (stdlib only) so the kernel runs even if everything else breaks.
"""
import os
import json

SCHEMA_VERSION = 1
ZAUDE_MARKER = "zaude-project"
VALID_MODES = ("shadow", "enforce")


def _real(p):
    """realpath that never raises (returns the input on failure)."""
    try:
        return os.path.realpath(p)
    except Exception:
        return p


def kill_switch_active():
    """Absolute, first-checked off-ramp [codex-SF3]."""
    try:
        if os.environ.get("ZAUDE_DISABLE") == "1":
            return True
        marker = os.path.join(os.path.expanduser("~"), ".zaude", "disabled")
        if os.path.isfile(marker):
            return True
    except Exception:
        # If we cannot even check the kill switch, fail OPEN by treating it as active.
        return True
    return False


def _try_load(d):
    """Load+validate <d>/.zaude/project.json. Returns a ProjectContext dict or None.

    Every failure mode (missing, garbled, wrong marker/schema, parent-owned, moved,
    bad mode) returns None so the caller fails open. [codex#2]
    """
    pj = os.path.join(d, ".zaude", "project.json")
    try:
        if not os.path.isfile(pj):
            return None
        with open(pj, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None  # garbled/unreadable -> fail open

    if not isinstance(data, dict):
        return None
    if data.get("zaude_marker") != ZAUDE_MARKER:
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        return None

    pr = data.get("project_root")
    if not isinstance(pr, str) or not pr:
        return None
    # The marker must claim THIS dir as its root (canonical, case-normalized compare). This
    # is what prevents a child checkout from binding to a parent's .zaude. [codex#3,#4, M3]
    if os.path.normcase(_real(pr)) != os.path.normcase(_real(d)):
        return None

    mode = data.get("enforcement_mode")
    if mode not in VALID_MODES:
        return None

    root = _real(d)
    return {
        "root": root,
        "zaude_dir": os.path.join(root, ".zaude"),
        "schema_version": SCHEMA_VERSION,
        "kernel_version": data.get("kernel_version"),
        "enforcement_mode": mode,
    }


# Files/dirs that mark an INDEPENDENT project root. If we cross one of these without
# finding a valid .zaude at-or-below it, we stop — so a non-onboarded nested project under
# an onboarded parent never binds to the parent's .zaude. [A2, sec-C1, codex-HIGH, cr-M1]
# (.git may be a FILE in worktrees/submodules, hence os.path.exists not isdir.)
_BOUNDARY_MARKERS = (".git", ".hg", ".svn", "package.json", "pyproject.toml",
                     "go.mod", "Cargo.toml")


def _is_boundary(d):
    for m in _BOUNDARY_MARKERS:
        if os.path.exists(os.path.join(d, m)):
            return True
    return False


def find_project(cwd):
    """Walk up from cwd looking for a VALID onboarded project, stopping at the first
    independent-project boundary. Returns a ProjectContext dict or None. Never raises.
    [codex#2,#3, A2]

    Boundary rule: at each level we FIRST check for a valid .zaude here; if found, bind.
    Otherwise, if this dir looks like an independent project root (a boundary marker), we
    stop and return None — we never bind to a .zaude that lives ABOVE an intervening repo.
    """
    try:
        start = _real(cwd) if cwd else _real(os.getcwd())
        if not os.path.isdir(start):
            start = os.path.dirname(start)  # a file path -> its containing dir

        cur = start
        seen = set()
        while True:
            rc = _real(cur)
            if os.path.normcase(rc) in seen:
                return None  # symlink/junction loop -> fail open [codex#4]
            seen.add(os.path.normcase(rc))

            proj = _try_load(rc)
            if proj is not None:
                return proj

            # Independent-project boundary with no valid .zaude here = not onboarded.
            if _is_boundary(rc):
                return None

            parent = os.path.dirname(rc)
            if parent == rc:
                return None  # filesystem root
            cur = parent
    except Exception:
        return None  # ANY failure -> fail open
