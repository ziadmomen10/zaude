"""
board.py (v0.2.0 / P4) — parallel board + autonomous multi-item loop, Approach A.

Each work item gets its OWN single-track signed sub-trace under `.zaude/items/<work_id>/`, so the
SACRED `state.reduce()` runs PER-ITEM, UNCHANGED. The board is therefore many independent
single-tracks + a derived index — the root trace stays the PM/board ledger (init + pm_* rows +
the NEW {"kind":"item_activate"} / {"kind":"active_set"} markers, which `reduce()` already ignores
as unknown kinds).

Design invariants (verified against the kernel this builds on):
- ONE HMAC key per project: `keys.get_key(root)` is keyed on the PROJECT ROOT (not the dir), so every
  sub-trace under the same root shares the key automatically — NO keys.py change, NO per-item keys.
- The sub-trace is a NORMAL trace: `trace.append_row(item_dir, row, root)` chains+MACs it exactly like
  the root, and `trace.read_trace(item_dir, root, verify=True)` verifies it. A forged sub-trace raises
  `TraceForged` just like the root (so the hook fails closed on it in enforce).
- `active_item_dir(zaude_dir, root)` / `active_item_id()` are TOTAL: they NEVER raise and return None on
  ANY problem, because the hook depends on them failing open to the root trace (today's behavior).
  `active_item_dir` binds SELECTION to the signed marker set (a committed item), not bare dir existence.
- A project with NO `.zaude/items/` dir never grows any of this (the legacy / back-compat path).

stdlib only.
"""
import os
import re

from . import trace
from . import state as st
from . import pm

ITEMS_DIRNAME = "items"
ACTIVE_FILE = "active"
BOARD_FILE = "board.json"

# A work id is a directory name under items/, so it MUST be a single plain token — no separators,
# no traversal, no drive qualifier (e.g. "C:foo"), no colon/dot/whitespace. Anchored, length-capped.
# pm.next_work_id emits ids like "ZA-2026-00001" which match; a hand-passed --id that doesn't match
# is rejected at every entry point. [HIGH: path-traversal hardening]
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


# ---------------------------------------------------------------- paths
def items_root(zaude_dir):
    return os.path.join(zaude_dir, ITEMS_DIRNAME)


def item_dir(zaude_dir, item_id):
    """The sub-trace directory for a work item, or None if the id is invalid OR the resolved path
    escapes items/ (defense-in-depth). A None return MUST be treated by callers as 'no such item'
    (the strict id check already rejects traversal; the realpath-containment is a belt-and-braces
    guard against symlinks / odd platform path joins). No trace I/O — only path resolution."""
    if not _valid_item_id(item_id):
        return None
    base = items_root(zaude_dir)
    cand = os.path.join(base, item_id)
    # realpath-contain: the resolved candidate must equal or live under realpath(items_base). This
    # catches anything the regex somehow let through plus symlink escapes. realpath never raises.
    try:
        rbase = os.path.realpath(base)
        rcand = os.path.realpath(cand)
    except Exception:
        return None
    if rcand != rbase and not rcand.startswith(rbase + os.sep):
        return None
    return cand


def _valid_item_id(item_id):
    """A work id must be a single plain token (str, non-empty, anchored to _ITEM_ID_RE) so it is safe
    as a directory name under items/ . Rejects path separators, "..", absolute paths, drive
    qualifiers like "C:foo", colons, dots, whitespace, NUL, empty, and non-str. (Ids come from
    pm.next_work_id like ZA-2026-00001; a hand-passed --id must not traverse.)"""
    if not isinstance(item_id, str) or not item_id:
        return False
    return _ITEM_ID_RE.match(item_id) is not None


# ---------------------------------------------------------------- active (TOTAL, never raises)
def active_item_id(zaude_dir):
    """Return the active work id from the one-line `active` file, or None on ANY problem (absent
    file, unreadable, empty, malformed id). NEVER raises — the hook's fail-open contract. An absent
    or empty file means root/legacy (today's behavior)."""
    try:
        p = os.path.join(zaude_dir, ACTIVE_FILE)
        if not os.path.isfile(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            val = f.read().strip()
        if not val or not _valid_item_id(val):
            return None
        return val
    except Exception:
        return None


def active_item_dir(zaude_dir, root):
    """Return the active item's sub-trace dir IFF an active id is set AND that id is a COMMITTED item
    (carries a signed {"kind":"item_activate"} marker on the ROOT trace) AND items/<id>/ exists, else
    None. TOTAL — never raises (the hook calls `active_item_dir(zd, root) or zd`, so None == today's
    root path). A set-but-missing active dir, OR an active pointer at an UNACTIVATED id (a crash-orphan
    dir / a copied-or-planted items/<id>/ sub-trace with no signed marker), returns None => fail-open
    to the root trace. SELECTION is thus bound to the signed marker set, never to bare dir existence,
    so an uncommitted item can never be gated/driven via the `active` file. [HIGH: selection-binding]"""
    try:
        iid = active_item_id(zaude_dir)
        if iid is None:
            return None
        if iid not in _marker_item_ids(zaude_dir, root):   # not a committed/signed item
            return None
        d = item_dir(zaude_dir, iid)            # None if id invalid / escapes items/
        if d and os.path.isdir(d):
            return d
        return None
    except Exception:
        return None


# ---------------------------------------------------------------- item lifecycle (root-locked)
def activate_item(zaude_dir, root, item_id):
    """Atomically activate a work item under the ROOT lock, with the root {"kind":"item_activate"}
    marker as the COMMIT POINT (written LAST). Returns the item dir.

    Atomicity contract [HIGH]: the WHOLE activate runs under ONE root lock. The order is:
      1. (re)create items/<id>/ and write its sub-trace `init` row + state.json,
      2. ONLY THEN append the root `item_activate` marker (the commit point).
    Item ENUMERATION is marker-derived (see list_item_ids), so a crash BEFORE step 2 leaves an
    orphaned items/<id>/ dir that everyone IGNORES (no marker => not an item). Re-running is then
    idempotent: if the marker already exists it is a no-op; otherwise it overwrites the partial dir
    and writes the marker exactly once. No half-activated item can ever be observed.
    """
    if not _valid_item_id(item_id):
        raise ValueError("invalid work id %r" % (item_id,))
    d = item_dir(zaude_dir, item_id)
    if d is None:
        raise ValueError("invalid work id %r" % (item_id,))
    lp = trace.acquire_lock(zaude_dir)
    try:
        # idempotent: a committed marker => already fully activated => no-op (never reset its state).
        if item_id in _marker_item_ids(zaude_dir, root):
            return d
        # no marker yet => this dir (if present) is at most a crash orphan; (re)init it from scratch
        # so a partial dir is healed, then COMMIT by appending the root marker last.
        os.makedirs(os.path.join(d, "artifacts"), exist_ok=True)
        _init_item_subtrace(d, root, item_id)
        trace.append_row(zaude_dir, {"kind": "item_activate", "item_id": item_id}, root)  # COMMIT
    finally:
        trace.release_lock(lp)
    return d


def _init_item_subtrace(d, root, item_id):
    """(Re)initialize the per-item sub-trace to a clean single-track: a fresh `init` row + state.json.
    Called only with no committed marker for this id (first activation OR healing a crash orphan), so
    overwriting any partial trace is safe — the partial was never observable. Truncates an existing
    trace.jsonl first so a re-init starts a clean chain."""
    tp = os.path.join(d, "trace.jsonl")
    try:
        if os.path.exists(tp):
            os.remove(tp)
    except OSError:
        pass
    trace.append_row(d, {"kind": "init", "root": root, "item_id": item_id}, root)
    _write_item_state(d, root)


def _marker_item_ids(zaude_dir, root):
    """The committed work ids: the set of ids carried by {"kind":"item_activate"} markers on the ROOT
    trace, in first-seen order, validated. This is the SOURCE OF TRUTH for which items exist — derived
    from the signed trace, never from a raw scandir of items/ (so crash orphans are ignored and an
    attacker-planted dir without a signed marker is not an item). TOTAL: returns [] on any problem."""
    out = []
    seen = set()
    try:
        rows = trace.read_trace(zaude_dir, root, verify=True)
    except Exception:
        return []
    for r in rows:
        if r.get("kind") == "item_activate":
            wid = r.get("item_id")
            if _valid_item_id(wid) and wid not in seen:
                seen.add(wid)
                out.append(wid)
    return out


def set_active(zaude_dir, root, item_id_or_none):
    """Record {"kind":"active_set","item_id":id|null} on the ROOT trace and write (or clear) the
    one-line `active` file. Passing None clears the active item (back to root/legacy). The ROOT lock
    serializes the marker + the file write together."""
    if item_id_or_none is not None:
        if not _valid_item_id(item_id_or_none):
            raise ValueError("invalid work id %r" % (item_id_or_none,))
        # SELECTION must be bound to a COMMITTED marker: you cannot focus an item that was never
        # activated (no signed item_activate marker), even if a items/<id>/ dir happens to exist on
        # disk (crash orphan / planted dir). [HIGH: selection-binding]
        if item_id_or_none not in _marker_item_ids(zaude_dir, root):
            raise ValueError("work id %s is not activated -- run item-activate first"
                             % (item_id_or_none,))
    lp = trace.acquire_lock(zaude_dir)
    try:
        trace.append_row(zaude_dir, {"kind": "active_set", "item_id": item_id_or_none}, root)
        p = os.path.join(zaude_dir, ACTIVE_FILE)
        if item_id_or_none is None:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        else:
            _atomic_write_text(p, item_id_or_none + "\n")
    finally:
        trace.release_lock(lp)
    return item_id_or_none


def _atomic_write_text(path, text):
    """Atomic single-line text write (the `active` pointer is a cache like state.json)."""
    import tempfile
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
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


# ---------------------------------------------------------------- per-item projection
def _projection_out(item_d, root):
    """Per-item projection in the same shape `cli._projection_out` writes for the root. Kept here so
    activate_item can seed state.json without importing cli (avoids a cycle)."""
    p = st.reduce(trace.read_trace(item_d, root, verify=True))
    return {
        "current_state": p["current_state"],
        "allowed_next_states": st.next_states(p["current_state"]),
        "risk_tier": p["risk_tier"],
        "artifacts": p["artifacts"],
        "waived_gates": sorted(p["waived_gates"]),
        "release_token_active": p["release_token_active"],
        "last_transition": p["last_transition"],
    }


def _write_item_state(item_d, root):
    trace.write_state(item_d, _projection_out(item_d, root))


# ---------------------------------------------------------------- item DoD predicate (factored out)
def item_done(item_d, root):
    """Per-item Definition-of-Done predicate, FACTORED OUT of cmd_dod (behavior-preserving): the
    item reached its flow's TERMINAL with the evidence that flow marks applicable. Flow-awareness is
    delegated to cli (FLOWS lives there); here we take the resolved spec via a late import to avoid a
    module cycle. Returns a dict {met, flow, terminal, lifecycle_state, has_passing_tests,
    has_verification_evidence, ...} so cmd_dod can render the SAME JSON it does today.

    NOTE: this predicate is the SINGLE-ITEM condition only (it does NOT check the intake column —
    that is a BOARD-level condition handled by board_dod / cmd_dod, preserving today's behavior)."""
    import cli  # late import: FLOWS / DEFAULT_FLOW / _state_index / active_flow live in cli
    proj = st.reduce(trace.read_trace(item_d, root, verify=True))
    arts = set(proj["artifacts"])
    cur = proj["current_state"]
    flow = cli.active_flow(item_d, root)
    spec = cli.FLOWS.get(flow, cli.FLOWS[cli.DEFAULT_FLOW])
    terminal = spec.get("terminal", "Released")
    applicable = spec.get("applicable", {})
    has_verify = "verification.json" in arts
    has_tests = "test-results.json" in arts
    need_tests = "Tested" in applicable
    need_verify = "Verified" in applicable
    tests_ok = has_tests if need_tests else True
    verify_ok = has_verify if need_verify else True
    done_state = cli._state_index(cur) >= cli._state_index(terminal)
    met = done_state and tests_ok and verify_ok
    return {
        "met": met,
        "flow": flow,
        "terminal": terminal,
        "lifecycle_state": cur,
        "has_passing_tests": has_tests,
        "has_verification_evidence": (has_verify if need_verify else "n/a"),
    }


# ---------------------------------------------------------------- board-level projections
def _root_board(zaude_dir, root):
    return pm.pm_board(trace.read_trace(zaude_dir, root, verify=True))


def list_item_ids(zaude_dir, root):
    """The existing work items, MARKER-DERIVED from the ROOT trace's {"kind":"item_activate"} markers
    (NOT a raw scandir of items/). An id appears only if it has a committed marker AND its sub-trace
    dir exists on disk — so a crash orphan (dir, no marker) is ignored, and a stale marker whose dir
    was wiped is skipped. Sorted for stable output. TOTAL: returns [] on any problem.

    Requires `root` (the project root) to read+verify the signed root trace — the marker set is the
    source of truth for enumeration, so it must be verified, not scandir'd."""
    out = []
    try:
        for wid in _marker_item_ids(zaude_dir, root):
            d = item_dir(zaude_dir, wid)
            if d and os.path.isdir(d) and os.path.isfile(os.path.join(d, "trace.jsonl")):
                out.append(wid)
    except Exception:
        return []
    return sorted(out)


def _promoted_work_ids(board):
    """Work ids that are PROMOTED features OR their child tasks/bugs (the deliverables a board-DoD
    must see done). Features carry no `parent`; children carry one. Spikes/chores are included too —
    every backlog item that isn't intake."""
    return [wid for wid in board["items"].keys()]


def board_dod(zaude_dir, root):
    """BOARD-level Definition-of-Done. met == the intake column is empty AND every promoted backlog
    item has an items/<id>/ sub-trace AND that sub-trace is item_done. Returns a diagnostics dict.

    This is the RIGHT-reason fix for the diagnosed bug: a board with an open intake is NOT done (the
    work hasn't been promoted/started yet), and a promoted item that was never activated is NOT done
    (no sub-trace, so no evidence). Legacy (no items dir, no promoted items) collapses to: met iff
    intake empty — which, combined with cmd_dod's root predicate, preserves today's single-track DoD.
    """
    board = _root_board(zaude_dir, root)
    open_intake = len(board["intake"])
    promoted = _promoted_work_ids(board)
    have = set(list_item_ids(zaude_dir, root))
    unactivated = [wid for wid in promoted if wid not in have]
    items_total = len(promoted)
    items_done = 0
    unfinished = []
    for wid in promoted:
        d = item_dir(zaude_dir, wid)
        if wid not in have or d is None:
            unfinished.append(wid)
            continue
        try:
            if item_done(d, root)["met"]:
                items_done += 1
            else:
                unfinished.append(wid)
        except Exception:
            unfinished.append(wid)
    met = (open_intake == 0) and (not unactivated) and (items_total == items_done)
    return {
        "met": met,
        "items_total": items_total,
        "items_done": items_done,
        "unactivated_promoted": unactivated,
        "unfinished_items": unfinished,
        "open_intake_items": open_intake,
    }


def board_next(zaude_dir, root):
    """Next BOARD-level action string for the autonomous multi-item loop, in priority order:
      1. an OPEN intake idea exists -> 'promote <ZI-id>' (the PM must turn ideas into work first)
      2. a promoted item with NO sub-trace -> 'item-activate --id <wid>' (start it)
      3. an activated item not yet active -> 'active-set --id <wid> then /znext' (focus + drive it)
      4. an active item not yet done -> '/znext' (keep driving the inner loop)
      5. all done + intake empty -> 'board-DoD MET'
    Read-only; the driver runs the printed action. Returns (action_str, done_bool)."""
    board = _root_board(zaude_dir, root)
    bd = board_dod(zaude_dir, root)
    if bd["met"]:
        return ("board-DoD MET", True)
    # 1. open intake -> promote it
    if board["intake"]:
        iid = board["intake"][0]["id"]
        return ("promote --intake %s" % iid, False)
    # 2. a promoted item with no sub-trace yet
    if bd["unactivated_promoted"]:
        return ("item-activate --id %s" % bd["unactivated_promoted"][0], False)
    # 3/4. an unfinished activated item: focus it (active-set) if it isn't the active one, else drive
    active = active_item_id(zaude_dir)
    for wid in bd["unfinished_items"]:
        if wid == active:
            return ("/znext", False)
    if bd["unfinished_items"]:
        return ("active-set --id %s then /znext" % bd["unfinished_items"][0], False)
    # nothing actionable surfaced but DoD not met (shouldn't normally happen) -> drive the active item
    return ("/znext", False)


# ---------------------------------------------------------------- derived board index (cache only)
def rebuild_board_index(zaude_dir, root):
    """Derive board.json (a DISPLAY cache, like state.json) from the signed sources: the root PM
    board + each item's per-item projection (via the unchanged reduce()). Rebuildable any time
    (used by `zaude repair`). Returns the written dict."""
    board = _root_board(zaude_dir, root)
    items = {}
    for wid in list_item_ids(zaude_dir, root):
        d = item_dir(zaude_dir, wid)
        if d is None:
            items[wid] = {"error": "InvalidItemId"}
            continue
        try:
            proj = st.reduce(trace.read_trace(d, root, verify=True))
            items[wid] = {
                "current_state": proj["current_state"],
                "risk_tier": proj["risk_tier"],
                "done": item_done(d, root)["met"],
            }
        except Exception as e:
            items[wid] = {"error": type(e).__name__}
    out = {
        "active": active_item_id(zaude_dir),
        "intake": [it["id"] for it in board["intake"]],
        "backlog": {wid: {"type": i.get("type"), "status": i.get("status"),
                          "parent": i.get("parent")}
                    for wid, i in board["items"].items()},
        "items": items,
    }
    trace.write_json_atomic(os.path.join(zaude_dir, BOARD_FILE), out)
    return out
