"""
paths.py — project resolution + the FAIL-OPEN safety probe.

This is the single most safety-critical file in the kernel. The Zaude hooks run on
EVERY project on this machine (including the 21 not onboarded). The contract is TRI-STATE
(resolve()), so the hook can fail closed on integrity failures without locking out the world:

  - VALID  : <root>/.zaude/project.json validates AND its canonical project_root == the
             resolved repo root  -> onboarded, gates run.
  - BROKEN : <root>/.zaude/project.json is PRESENT but unreadable / empty / garbled
             (unparseable)        -> the hook FAILS CLOSED (deny in any mode) because the
             enforcement_mode can't be read. Symmetric with a corrupt/forged trace. The kill
             switch (ZAUDE_DISABLE=1 / ~/.zaude/disabled) is the escape. [codex fail-open #1]
  - NONE   : no marker, OR a marker that still PARSES but isn't a valid claim for this dir
             (not-our-marker, a DIFFERENT root like a fresh `git clone`, schema drift, bad
             mode)                -> the hook FAILS OPEN (does nothing, exits 0). [codex#2,#3,#4]

find_project() stays a valid-or-None wrapper for the CLI; only resolve()/the hook see BROKEN.
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


def _reject_const(_):
    """json.loads parse_constant hook: NaN/Infinity/-Infinity are NOT standard JSON, so a marker
    that is exactly one of them is garbled (-> _Broken), not a parseable mismatch. [codex review]"""
    raise ValueError("non-standard JSON constant")


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


class _Broken:
    """A `.zaude/project.json` that is PRESENT but UNUSABLE — unreadable, empty, or garbled
    (unparseable) JSON. Distinct from absent (no file) and from a marker that still parses but
    isn't a valid claim for this dir. The HOOK fails CLOSED on a _Broken marker (symmetric with a
    corrupt/forged trace) because its enforcement_mode lives inside the corrupt file and cannot be
    read — so we cannot prove the project was in shadow. Absent / parses-but-mismatched stays
    fail-OPEN. [codex fail-open #1, co-plan]"""
    __slots__ = ("reason",)

    def __init__(self, reason):
        self.reason = reason


def _load_marker(d):
    """SINGLE-READ tri-state loader for <d>/.zaude/project.json — distinguishes absent vs broken
    vs valid from ONE open() to avoid a TOCTOU fail-open (codex co-plan #1). Returns:
      - a ProjectContext dict  -> VALID marker that claims this dir              (onboarded)
      - a _Broken(reason)      -> file PRESENT but unreadable / empty / garbled  (hook FAILS CLOSED)
      - None                   -> ABSENT, or a marker that still PARSES but isn't a valid claim
                                  for this dir (not-our-marker, wrong schema, a DIFFERENT root
                                  such as a fresh `git clone`, bad mode)         (hook FAILS OPEN)
    Never raises.

    Why only unparseable/empty/unreadable fails closed (and everything that still parses to JSON
    is treated EXACTLY as the original validator did): truncation, garbled bytes and bad perms are
    the realistic ways a marker silently loses enforcement, and corruption never yields *valid*
    JSON. Keeping every parseable case fail-open means `git clone` (markers carry an absolute
    project_root, foreign on a new checkout), schema drift across kernel versions, and unrelated
    tools are NEVER locked out. [codex co-plan #1,#3,#4]"""
    pj = os.path.join(d, ".zaude", "project.json")
    try:
        with open(pj, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        # open() raises FileNotFoundError for BOTH "no entry" and "DANGLING SYMLINK" (entry exists,
        # target missing). The latter is a PRESENT-but-unusable marker -> must fail CLOSED, not open.
        # lstat does not follow the link: it succeeds for a dangling symlink, raises for true absence.
        # [codex review CRITICAL]
        try:
            os.lstat(pj)
            return _Broken("unreadable")  # dangling symlink / special entry: present but unusable
        except Exception:
            return None                   # genuinely absent -> fail open
    except Exception:
        return _Broken("unreadable")      # is-a-dir / perms / OS error: present but unusable
    # A file WAS present and read. From here ANY unexpected error => _Broken (present-but-unusable),
    # so the "never raises" contract holds even for `scan-markers`, which calls us directly without
    # resolve()'s outer guard. [codex review MEDIUM]
    try:
        if not raw.strip():
            return _Broken("empty")       # truncated / partial write
        try:
            # parse_constant rejects NaN/Infinity/-Infinity — not standard JSON, so a marker that is
            # exactly that is garbled, not a parseable mismatch. [codex review MEDIUM]
            data = json.loads(raw, parse_constant=_reject_const)
        except Exception:
            return _Broken("badjson")     # garbled bytes -> the primary corruption/tamper vector

        # --- parsed OK: behave EXACTLY as the original validator (fail OPEN on any mismatch), so
        #     clones / schema drift / other tools that happen to use the path are never locked out ---
        if not isinstance(data, dict):
            return None
        if data.get("zaude_marker") != ZAUDE_MARKER:
            return None
        if data.get("schema_version") != SCHEMA_VERSION:
            return None

        pr = data.get("project_root")
        if not isinstance(pr, str) or not pr:
            return None
        # The marker must claim THIS dir as its root (canonical, case-normalized compare — handles
        # Windows casing). This prevents a child checkout from binding to a parent's .zaude, and a
        # fresh clone (foreign absolute root) from failing closed. [codex#3,#4, M3]
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
    except Exception:
        # a file was present but validation hit an unexpected error -> present-but-unusable.
        return _Broken("invalid")


def _try_load(d):
    """Back-compat: a valid ProjectContext dict for <d>, else None (broken OR absent both -> None).
    The broken-vs-absent distinction is only consumed by resolve()/the hook."""
    m = _load_marker(d)
    return m if isinstance(m, dict) else None


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


def resolve(cwd):
    """Walk up from cwd and return a TRI-STATE for the hook (never raises):
      {"status": "onboarded", "ctx": <ProjectContext>}                 -> proceed
      {"status": "broken", "broken_root": <dir>, "reason": <str>}      -> hook FAILS CLOSED
      {"status": "none"}                                               -> not onboarded, FAIL OPEN

    Boundary rule (unchanged): at each level we FIRST load the marker here; a VALID one binds.
    A BROKEN one (present-but-corrupt) STOPS the walk and fails closed — we never bind a parent's
    `.zaude` *past* a broken child marker (a present marker is an ownership claim). Otherwise, if
    this dir is an independent-project boundary, we stop (none); else we walk up. Symlink loop /
    filesystem root / any exception -> none (fail open). [codex#2,#3, A2, fail-open #1]"""
    try:
        start = _real(cwd) if cwd else _real(os.getcwd())
        if not os.path.isdir(start):
            start = os.path.dirname(start)  # a file path -> its containing dir

        cur = start
        seen = set()
        while True:
            rc = _real(cur)
            if os.path.normcase(rc) in seen:
                return {"status": "none"}  # symlink/junction loop -> fail open [codex#4]
            seen.add(os.path.normcase(rc))

            m = _load_marker(rc)
            if isinstance(m, dict):
                return {"status": "onboarded", "ctx": m}
            if isinstance(m, _Broken):
                # present-but-corrupt marker here = onboarded-but-broken. Stop; fail closed.
                return {"status": "broken", "broken_root": rc, "reason": m.reason}

            # Independent-project boundary with no marker here = not onboarded.
            if _is_boundary(rc):
                return {"status": "none"}

            parent = os.path.dirname(rc)
            if parent == rc:
                return {"status": "none"}  # filesystem root
            cur = parent
    except Exception:
        return {"status": "none"}  # ANY failure -> fail open


def find_project(cwd):
    """Resolve a VALID onboarded project for `cwd`, else None. Back-compat wrapper over resolve()
    — a broken (present-but-corrupt) marker returns None here, so existing CLI callers behave
    exactly as before; only the HOOK uses resolve() to fail CLOSED on a broken marker. Never
    raises. [codex#2,#3, A2]"""
    r = resolve(cwd)
    return r.get("ctx") if r.get("status") == "onboarded" else None
