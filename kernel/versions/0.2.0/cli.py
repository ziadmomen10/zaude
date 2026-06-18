"""
cli.py (v0.2.0) — the deterministic worker behind the slash commands. Commands COMMIT
transitions (agents only draft). Each transition needs its required artifact; /review, /verify
and /ship enforce the quality chain; /waive is the ONLY way to bypass a gate (and it is logged).
"""
import os
import sys
import json
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import (paths, trace, state as st, pm, onboard, gates, codex, agents,  # noqa: E402
                 persona, router, memory)


def _kernel_version():
    try:
        with open(os.path.join(os.path.expanduser("~"), ".zaude", "kernel", "CURRENT"),
                  "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def _zaude_dir(root):
    return os.path.join(root, ".zaude")


def _project_kernel_version(zaude_dir):
    try:
        with open(os.path.join(zaude_dir, "project.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("kernel_version")
    except Exception:
        return None


def _projection_out(zaude_dir, root):
    p = st.reduce(trace.read_trace(zaude_dir, root, verify=True))
    return {
        "current_state": p["current_state"],
        "allowed_next_states": st.next_states(p["current_state"]),
        "kernel_version": _project_kernel_version(zaude_dir),
        "risk_tier": p["risk_tier"],
        "artifacts": p["artifacts"],
        "waived_gates": sorted(p["waived_gates"]),
        "release_token_active": p["release_token_active"],
        "last_transition": p["last_transition"],
    }


def _refresh_state(zaude_dir, root):
    trace.write_state(zaude_dir, _projection_out(zaude_dir, root))


def _write_artifact(zaude_dir, name, obj):
    trace.write_json_atomic(os.path.join(zaude_dir, "artifacts", name), obj)


def _read_artifact(zaude_dir, name):
    try:
        with open(os.path.join(zaude_dir, "artifacts", name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _commit(zaude_dir, root, frm, to, command, artifact_name=None, artifact_obj=None,
            extra_rows=None):
    lp = trace.acquire_lock(zaude_dir)
    committed = False
    try:
        cur = st.reduce(trace.read_trace(zaude_dir, root, verify=True))["current_state"]
        if cur != frm:
            sys.stderr.write("refused: %s requires state=%s but state=%s\n" % (command, frm, cur))
            return 3
        if not st.can_transition(frm, to):
            sys.stderr.write("refused: illegal transition %s -> %s\n" % (frm, to))
            return 3
        if artifact_name is not None:
            _write_artifact(zaude_dir, artifact_name, artifact_obj)
        for r in (extra_rows or []):
            trace.append_row(zaude_dir, r, root)
        trace.append_row(zaude_dir, {"kind": "transition", "from": frm, "to": to,
                                     "command": command, "artifact": artifact_name}, root)
        committed = True
        try:
            _refresh_state(zaude_dir, root)
        except Exception as e:
            sys.stderr.write("note: committed; projection refresh failed (%s); `zaude repair`.\n" % e)
    finally:
        trace.release_lock(lp)
    if committed:
        print("OK: %s  %s -> %s" % (command, frm, to))
        return 0
    return 1


# ---------------------------------------------------------------- resolve
def _resolve(args):
    proj = paths.find_project(args.path or os.getcwd())
    if proj is None:
        sys.stderr.write("not an onboarded Zaude project\n")
        sys.exit(4)
    return proj["zaude_dir"], proj["root"]


# ---------------------------------------------------------------- commands
def cmd_init(args):
    root = paths._real(args.path or os.getcwd())
    zd = _zaude_dir(root)
    if not getattr(args, "force", False) and paths.find_project(root) is not None:
        sys.stderr.write("refused: %s already onboarded. --force to re-init.\n" % root)
        return 3
    os.makedirs(os.path.join(zd, "artifacts"), exist_ok=True)
    trace.write_json_atomic(os.path.join(zd, "project.json"), {
        "zaude_marker": paths.ZAUDE_MARKER, "schema_version": paths.SCHEMA_VERSION,
        "project_root": root, "kernel_version": _kernel_version(),
        "enforcement_mode": args.mode})
    _write_artifact(zd, "request.json", {"id": "REQ-INTAKE", "text": args.text, "source": "operator"})
    if not trace.read_trace(zd, root, verify=False):
        trace.append_row(zd, {"kind": "init", "root": root, "mode": args.mode}, root)
    _refresh_state(zd, root)
    print("initialized %s (mode=%s)" % (zd, args.mode))
    return 0


def _simple(frm, to, command, artifact, build_obj):
    def fn(args):
        zd, root = _resolve(args)
        return _commit(zd, root, frm, to, command, artifact, build_obj(args))
    return fn


def cmd_classify_risk(args):
    zd, root = _resolve(args)
    return _commit(zd, root, "Designed", "RiskClassified", "/classify-risk", "risk.json",
                   {"tier": args.tier}, extra_rows=[{"kind": "risk", "tier": args.tier}])


_FAST_CHAIN = [("Intake", "Clarified", "/clarify", "requirements.json"),
               ("Clarified", "Prioritized", "/prioritize", "priority.json"),
               ("Prioritized", "Planned", "/plan", "plan.json"),
               ("Planned", "Designed", "/design", "design.json"),
               ("Designed", "RiskClassified", "/classify-risk", "risk.json"),
               ("RiskClassified", "Approved", "/approve", "approval.json")]

_SHIP_CHAIN = [("Approved", "Implemented", "/implement", "impl.json"),
               ("Implemented", "Tested", "/test", "test-results.json"),
               ("Tested", "Reviewed", "/review", "review-ledger.json"),
               ("Reviewed", "Verified", "/verify", "verification.json"),
               ("Verified", "Shippable", "/shippable", "shippable.json")]


def cmd_fast(args):
    """Fast lane for small/low-risk work: auto-complete Intake->Approved in ONE command so
    coding flows immediately. The full chain is still recorded in the trace (honest audit),
    you just don't run 6 commands. High-risk (T3/T4) is refused -> use the full chain. [Deen]"""
    zd, root = _resolve(args)
    if args.tier in gates.HIGH_RISK:
        sys.stderr.write("refused: fast-lane is for low/medium risk; %s needs the full chain "
                         "(/design -> /classify-risk -> /approve).\n" % args.tier)
        return 3
    lp = trace.acquire_lock(zd)
    try:
        cur = st.reduce(trace.read_trace(zd, root, verify=True))["current_state"]
        if cur != "Intake":
            sys.stderr.write("refused: fast-lane starts at Intake (state=%s)\n" % cur); return 3
        trace.append_row(zd, {"kind": "risk", "tier": args.tier}, root)
        for frm, to, cmd, art in _FAST_CHAIN:
            _write_artifact(zd, art, {"fast_lane": True, "note": args.note, "tier": args.tier})
            trace.append_row(zd, {"kind": "transition", "from": frm, "to": to,
                                  "command": cmd, "artifact": art, "fast": True}, root)
        _refresh_state(zd, root)
    finally:
        trace.release_lock(lp)
    print("fast-lane (%s): Intake -> Approved in one step — coding unblocked. '%s'" % (args.tier, args.note))
    return 0


def cmd_fast_ship(args):
    """Fast ship for small/low-risk work: Approved -> Released in ONE command. The ONE gate that
    stays is the evidence gate — it REFUSES to ship if tests didn't pass. High-risk uses the
    full review+verify chain. [Deen: light, but never ship broken]"""
    zd, root = _resolve(args)
    proj = st.reduce(trace.read_trace(zd, root, verify=True))
    if proj.get("risk_tier") in gates.HIGH_RISK:
        sys.stderr.write("refused: fast-ship is low/medium only; %s needs the full chain.\n"
                         % proj.get("risk_tier")); return 3
    if int(args.tested_exit) != 0:
        sys.stderr.write("refused: tests did not pass (exit %s) — fast-ship will not ship "
                         "broken code.\n" % args.tested_exit); return 3
    if proj["current_state"] != "Approved":
        sys.stderr.write("refused: fast-ship starts at Approved (state=%s)\n" % proj["current_state"])
        return 3
    arts = {"impl.json": {"fast": True},
            "test-results.json": {"cmd": args.tested_cmd, "exit": 0},
            "review-ledger.json": {"unresolved_critical_high": 0, "fast": True},
            "verification.json": {"built": "ok", "health": "tests green", "fast": True},
            "shippable.json": {"all_gates": "green"}}
    lp = trace.acquire_lock(zd)
    try:
        for frm, to, cmd, art in _SHIP_CHAIN:
            _write_artifact(zd, art, arts[art])
            trace.append_row(zd, {"kind": "transition", "from": frm, "to": to,
                                  "command": cmd, "artifact": art, "fast": True}, root)
        _write_artifact(zd, "release.json", {"deploy_id": args.deploy_id, "fast": True})
        trace.append_row(zd, {"kind": "release_token", "expires_at": time.time() + 3600,
                              "scope": "deploy"}, root)
        trace.append_row(zd, {"kind": "transition", "from": "Shippable", "to": "Released",
                              "command": "/ship", "artifact": "release.json", "fast": True}, root)
        _refresh_state(zd, root)
    finally:
        trace.release_lock(lp)
    print("fast-ship (%s): Approved -> Released. tests passed (exit 0); deploy token issued."
          % (proj.get("risk_tier") or "low"))
    return 0


def _seat(outcome, verdict=None, summary=None, reason=None, retry_at=None, now=None, **extra):
    """A codex review-seat record. `enforced` means ONLY 'codex actually participated' (outcome ==
    used) — never claimed for absence/skip/no-credit (codex-review-MEDIUM). All keys present so the
    ledger schema is stable."""
    s = {"outcome": outcome, "verdict": verdict, "summary": summary, "reason": reason,
         "retry_at": retry_at, "checked_at": now or time.time(), "enforced": (outcome == "used")}
    s.update(extra)
    return s


def _codex_review_seat(zd, args, tier):
    """Build the honest, NON-BLOCKING codex seat for the review ledger. NEVER refuses and NEVER
    changes the exit code — codex is best-effort. The whole body is guarded so an unexpected raise
    degrades to a benign 'unavailable' record instead of crashing /review (the "never raises into
    the cycle" guarantee is total, not emergent). [L13/graceful-codex]"""
    now = time.time()
    try:
        mode = (getattr(args, "codex", "auto") or "auto")
        verdict = getattr(args, "codex_verdict", None)
        summary = (getattr(args, "codex_summary", "") or "")[:500]
        err = getattr(args, "codex_error", None)
        retry_arg = getattr(args, "codex_retry_at", None)

        # 1. Explicit operator skip wins over everything else (incl. a stray verdict) — honest:
        #    the operator turned codex off for THIS review. (codex-review-MEDIUM: off must win.)
        if mode in ("off", "never"):
            sys.stderr.write("codex: skipped by --codex %s for this review; continuing.\n" % mode)
            return _seat("skipped", reason=mode, now=now)

        # 2. Below T3 codex isn't part of the panel (light by default).
        if tier not in gates.HIGH_RISK:
            return _seat("skipped", reason="low_risk", now=now)

        # 3. Driver ran codex and got a verdict -> honest 'used'. Codex is clearly back -> clear
        #    any no-credit backoff so it re-participates next time.
        if verdict:
            codex.clear_retry(zd)
            return _seat("used", verdict=verdict, summary=summary, now=now)

        # 4. Driver ran codex but it FAILED (quota / rate-limit / auth) and reported the error ->
        #    record honestly AND arm the no-credit backoff so codex AUTO-RESUMES when the reset
        #    window passes (the user's explicit requirement). [codex-review-HIGH wired here]
        if err:
            cls = codex.classify_error(1, err, now=now)
            # explicit --codex-retry-at wins, but a BAD value must not discard a valid hint
            # parsed from codex's stderr (codex re-review LOW).
            ra = codex.parse_retry_at(retry_arg) if retry_arg else None
            if ra is None:
                ra = cls.get("retry_at")
            if cls["reason"] in (codex.QUOTA, codex.RATE_LIMIT):
                codex.note_no_credit(zd, cls["reason"], ra)
                sys.stderr.write("codex: %s — continuing without it; will auto-resume%s.\n"
                                 % (cls["reason"], " at the retry window" if ra else
                                    " on the next review"))
                return _seat("no_credit", reason=cls["reason"], retry_at=ra, now=now)
            sys.stderr.write("codex: error (%s) — continuing without it.\n" % cls["reason"])
            return _seat("unavailable", reason=cls["reason"], now=now)

        # 5. No verdict/err: honor a live no-credit backoff (don't hammer a rate-limited provider;
        #    due_now() returns True again once the stored retry_at passes -> auto-resume).
        status = codex.read_status(zd)
        if not codex.due_now(status, now):
            r = status.get("retry") or {}
            sys.stderr.write("codex: in a no-credit/rate-limit backoff — continuing without it "
                             "(auto-resumes at the retry window).\n")
            return _seat("no_credit", reason=r.get("reason"), retry_at=r.get("retry_at"), now=now)

        # 6. Probe availability for the honest record + the soft "you have codex, use it" nudge.
        pr = codex.probe()
        if pr.get("status") == codex.READY:
            loud = (mode == "on")
            msg = ("codex is AVAILABLE and this is %s — run it and pass --codex-verdict "
                   "pass|concerns|fail (recorded as available-but-not-run).\n" % tier)
            sys.stderr.write(("NUDGE: " + msg) if loud else ("codex: " + msg))
            return _seat("skipped", reason="available_not_run", now=now,
                         version=pr.get("version"), auth_source=pr.get("auth_source"))
        if pr.get("status") == codex.PRESENT_NOAUTH:
            sys.stderr.write("codex: installed but not logged in — continuing without it. Run "
                             "`codex login` or drop a token at ~/.zaude/secrets/codex.\n")
            return _seat("unavailable", reason="present_noauth", now=now)
        sys.stderr.write("codex: not installed — continuing without it.\n")
        return _seat("unavailable", reason="missing", now=now)
    except Exception as e:   # the cycle must NEVER fail because of codex
        try:
            sys.stderr.write("codex: seat error (%s) — continuing without it.\n" % str(e)[:80])
        except Exception:
            pass
        return _seat("unavailable", reason="seat_error", now=now)


def cmd_review(args):
    """Tested -> Reviewed. Records the GRACEFUL codex seat (best-effort; never blocks). The ship
    gate still reads only `unresolved_critical_high`, so a codex 'fail' the driver wants to honor
    must be reflected there by the driver — codex never sets the gate by itself."""
    zd, root = _resolve(args)
    tier = st.reduce(trace.read_trace(zd, root, verify=True))["risk_tier"]
    unresolved = int(args.unresolved)
    seat = _codex_review_seat(zd, args, tier)
    obj = {"findings_summary": args.summary, "unresolved_critical_high": unresolved,
           "risk_tier_at_review": tier, "review_seats": {"codex": seat}}
    return _commit(zd, root, "Tested", "Reviewed", "/review", "review-ledger.json", obj)


def cmd_verify(args):
    zd, root = _resolve(args)
    obj = {"built_artifact_check": args.built, "health": args.health, "live_probe": args.probe}
    return _commit(zd, root, "Reviewed", "Verified", "/verify", "verification.json", obj)


def cmd_ship(args):
    """Shippable -> Released. Refuses unless the review ledger is CLEAN and verification
    exists; issues a release-token that unblocks deploy commands. [R7]"""
    zd, root = _resolve(args)
    ledger = _read_artifact(zd, "review-ledger.json")
    if not ledger or ledger.get("unresolved_critical_high", 1) != 0:
        sys.stderr.write("refused: /ship blocked — review ledger missing or has unresolved "
                         "CRITICAL/HIGH findings.\n")
        return 3
    if not _read_artifact(zd, "verification.json"):
        sys.stderr.write("refused: /ship blocked — no verification.json (run /verify).\n")
        return 3
    token_row = {"kind": "release_token", "expires_at": time.time() + 3600, "scope": "deploy"}
    rel = {"deploy_id": args.deploy_id, "health": "pending", "rollback_path": args.rollback}
    return _commit(zd, root, "Shippable", "Released", "/ship", "release.json", rel,
                   extra_rows=[token_row])


def cmd_waive(args):
    zd, root = _resolve(args)
    lp = trace.acquire_lock(zd)
    try:
        trace.append_row(zd, {"kind": "waiver", "gate": args.gate, "reason": args.reason,
                              "approved_by": args.by, "expires_at": None}, root)
        _refresh_state(zd, root)
    finally:
        trace.release_lock(lp)
    print("waiver recorded for gate=%s (by %s)" % (args.gate, args.by))
    return 0


def cmd_onboard(args):
    """Scaffold a project INTO the framework: .zaude state + vault + git. [L11]"""
    root = paths._real(args.path or os.getcwd())
    zd = _zaude_dir(root)
    if paths.find_project(root) is None:
        os.makedirs(os.path.join(zd, "artifacts"), exist_ok=True)
        trace.write_json_atomic(os.path.join(zd, "project.json"), {
            "zaude_marker": paths.ZAUDE_MARKER, "schema_version": paths.SCHEMA_VERSION,
            "project_root": root, "kernel_version": _kernel_version(),
            "enforcement_mode": args.mode, "slug": args.slug})
        _write_artifact(zd, "request.json", {"id": "REQ-INTAKE", "text": args.text, "source": "operator"})
        if not trace.read_trace(zd, root, verify=False):
            trace.append_row(zd, {"kind": "init", "root": root, "mode": args.mode}, root)
        _refresh_state(zd, root)
    vd, created = onboard.scaffold_vault(root, args.slug, args.stack, args.text)
    gited = onboard.git_init(root)
    print("onboarded '%s' (%s)" % (args.slug, args.stack))
    print("  state : %s (mode=%s)" % (_projection_out(zd, root)["current_state"], args.mode))
    print("  vault : %s  (%d files scaffolded)" % (os.path.relpath(vd, root), len(created)))
    print("  git   : %s" % ("initialized" if gited else "already a repo"))
    print("  pm    : local backlog ready (offline — provide a GitHub token to sync to Projects v2)")
    return 0


def _board(zd, root):
    return pm.pm_board(trace.read_trace(zd, root, verify=True))


def cmd_pm_add(args):
    zd, root = _resolve(args)
    iid = pm.next_intake_id(_board(zd, root))
    lp = trace.acquire_lock(zd)
    try:
        trace.append_row(zd, pm.intake_row(iid, args.note), root)
    finally:
        trace.release_lock(lp)
    print("intake %s added: %s" % (iid, pm._title_from(args.note)))
    return 0


def cmd_promote(args):
    zd, root = _resolve(args)
    board = _board(zd, root)
    if args.intake not in board["_all_intakes"]:
        sys.stderr.write("no such intake %s\n" % args.intake); return 3
    if board["_all_intakes"][args.intake]["promoted"]:
        sys.stderr.write("intake %s already promoted\n" % args.intake); return 3
    work_id = pm.next_work_id(board)
    tasks = [t.strip() for t in (args.tasks or "").split(";") if t.strip()]
    bugs = [b.strip() for b in (args.bugs or "").split(";") if b.strip()]
    child_ids = ["%s-%d" % (work_id, i + 1) for i in range(len(tasks) + len(bugs))]
    rows = pm.promote_rows(args.intake, work_id, args.title, args.story, args.ac, tasks, bugs,
                           child_ids, priority=args.priority, risk=args.risk)
    lp = trace.acquire_lock(zd)
    try:
        for r in rows:
            trace.append_row(zd, r, root)
    finally:
        trace.release_lock(lp)
    print("promoted %s -> %s  (Feature: %s)" % (args.intake, work_id, args.title))
    print("  user story: %s" % args.story)
    print("  children:   %d tech-tasks, %d bugs" % (len(tasks), len(bugs)))
    return 0


def cmd_pm_move(args):
    zd, root = _resolve(args)
    lp = trace.acquire_lock(zd)
    try:
        trace.append_row(zd, {"kind": "pm_move", "work_id": args.work_id, "to": args.to}, root)
    finally:
        trace.release_lock(lp)
    print("board: %s -> %s" % (args.work_id, args.to))
    return 0


# Board-affecting trace kinds (lifecycle status + intake/promote/workitem/move). Used to detect a
# board that has drifted from GitHub since the last /pm-sync (finding #3.1). [L13]
_PM_BOARD_KINDS = ("transition", "pm_intake", "pm_promote", "pm_workitem", "pm_move")


def _pm_unsynced(rows):
    """Count board-affecting trace rows appended AFTER the last `pm_synced` row — i.e. unsynced
    changes the GitHub board has not yet seen. 0 = board is in sync (or nothing to sync)."""
    last = -1
    for i, r in enumerate(rows):
        if r.get("kind") == "pm_synced":
            last = i
    return sum(1 for r in rows[last + 1:] if r.get("kind") in _PM_BOARD_KINDS)


def cmd_board(args):
    zd, root = _resolve(args)
    rows = trace.read_trace(zd, root, verify=True)
    n_stale = _pm_unsynced(rows)
    if n_stale:
        print("! board is STALE — %d change(s) since the last /pm-sync. Run /pm-sync to push them "
              "to GitHub.\n" % n_stale)
    b = _board(zd, root)
    print("INTAKE  (Ziad's column — drop ideas here):")
    print("  (empty)" if not b["intake"] else "", end="")
    for it in b["intake"]:
        print("  %-6s %s" % (it["id"], it["title"]))
    print("BACKLOG (agent-managed):")
    feats = [(w, i) for w, i in b["items"].items() if i["type"] == "feature"]
    print("  (empty)" if not feats else "", end="")
    for w, i in feats:
        print("  [FEATURE]  %-16s %s   <%s>" % (w, i["title"], i["status"]))
        for cw, ci in b["items"].items():
            if ci.get("parent") == w:
                print("     [%-9s] %-18s %s" % (ci["type"], cw, ci["title"]))
    return 0


def cmd_dod(args):
    """Definition-of-Done / autonomous-loop end-condition. DoD = the work reached Released/Closed
    WITH real evidence (passing tests + verification) AND the intake column is empty. This is
    'tier-4 as DoD' — the loop stops on real done-with-evidence, NOT on 'looks healthy'. Exit 0 =
    DoD met (loop may stop); exit 2 = keep the loop running. [Deen: tier-4=DoD, loop end-condition]"""
    zd, root = _resolve(args)
    proj = st.reduce(trace.read_trace(zd, root, verify=True))
    arts = set(proj["artifacts"])
    cur = proj["current_state"]
    has_verify = "verification.json" in arts
    has_tests = "test-results.json" in arts
    done_state = cur in ("Released", "Closed")
    open_intake = len(_board(zd, root)["intake"])
    dod = done_state and has_verify and has_tests and open_intake == 0
    print(json.dumps({
        "dod_met": dod,
        "lifecycle_state": cur,
        "has_passing_tests": has_tests,
        "has_verification_evidence": has_verify,
        "open_intake_items": open_intake,
        "loop_should_continue": not dod,
        "verdict": "DoD MET — tier-4 done with evidence; loop may stop"
                   if dod else "NOT done — keep the loop running (no 'looks healthy' stop)",
    }, indent=2))
    return 0 if dod else 2


def _pm_dir(zd):
    d = os.path.join(zd, "pm")
    os.makedirs(d, exist_ok=True)
    return d


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _slug(zd):
    try:
        with open(os.path.join(zd, "project.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("slug")
    except Exception:
        return None


def cmd_pm_init(args):
    """Provision the GitHub Projects v2 board: repo + labels + Intake-first Status column +
    Type/Priority/Risk/work_id fields. Stores NON-secret config in .zaude/pm/. [L13]"""
    zd, root = _resolve(args)
    from lib import pm_github
    if not pm_github.have_token():
        sys.stderr.write("no GitHub token; offline local backlog only.\n"); return 1
    cfg = pm_github.provision(args.login, args.repo, args.title)
    pmd = _pm_dir(zd)
    trace.write_json_atomic(os.path.join(pmd, "github.json"), cfg)
    if not os.path.exists(os.path.join(pmd, "github-map.json")):
        trace.write_json_atomic(os.path.join(pmd, "github-map.json"), {})
    print("pm board provisioned (Intake-first columns + labels + fields): %s" % cfg["url"])
    return 0


def cmd_pm_sync(args):
    """Push the local board to GitHub (create/update real issues + labels + columns + fields).
    Idempotent. Token stays in the secret backend; only the URL is recorded to the trace. [L13]"""
    zd, root = _resolve(args)
    from lib import pm_github
    if not pm_github.have_token():
        sys.stderr.write("no GitHub token; offline.\n"); return 1
    pmd = _pm_dir(zd)
    cfg = _load_json(os.path.join(pmd, "github.json"), None)
    if cfg is None:
        if not (args.login and args.repo):
            sys.stderr.write("first sync needs --login and --repo (or run pm-init first).\n"); return 3
        cfg = pm_github.provision(args.login, args.repo, args.title or "Zaude — Product Backlog")
        trace.write_json_atomic(os.path.join(pmd, "github.json"), cfg)
    board = _board(zd, root)
    for _wid, i in board["items"].items():
        if i["type"] == "feature":
            i["slug"] = _slug(zd) or "project"
    mapp = os.path.join(pmd, "github-map.json")
    # hold the lock across the whole sync so two pm-sync runs can't race the map [codex]
    lp = trace.acquire_lock(zd, timeout=10.0, stale_after=180.0)
    try:
        mapping = _load_json(mapp, {})
        persist = lambda m: trace.write_json_atomic(mapp, m)  # noqa: E731 — incremental save
        try:
            mapping, n = pm_github.sync(cfg, board, mapping, persist=persist)
        except pm_github.GitHubError as e:
            trace.write_json_atomic(mapp, mapping)  # keep partial progress so a re-run resumes
            sys.stderr.write("pm-sync incomplete: %s (re-run `pm-sync` to resume)\n" % e)
            return 1
        trace.write_json_atomic(mapp, mapping)
        trace.append_row(zd, {"kind": "pm_synced", "project_url": cfg["url"], "items": n}, root)
    finally:
        trace.release_lock(lp)
    print("synced %d items -> %s" % (n, cfg["url"]))
    return 0


def cmd_pm_pull(args):
    """Reconcile PM-owned business edits from GitHub back into the trace (PM-wins for
    Priority/Risk; lifecycle Status is trace-owned and not imported). [L13 bidirectional]"""
    zd, root = _resolve(args)
    from lib import pm_github
    pmd = _pm_dir(zd)
    cfg = _load_json(os.path.join(pmd, "github.json"), None)
    if cfg is None:
        sys.stderr.write("no board config; run pm-init first.\n"); return 1
    mapping = _load_json(os.path.join(pmd, "github-map.json"), {})
    try:
        actions = pm_github.pull(cfg, _board(zd, root), mapping)
    except pm_github.GitHubError as e:
        sys.stderr.write("pm-pull failed: %s\n" % e); return 1
    if not actions:
        print("pm-pull: already in sync (no PM edits to import)"); return 0
    lp = trace.acquire_lock(zd)
    try:
        for a in actions:
            if a.get("conflict"):   # both sides changed -> record, don't auto-overwrite
                trace.append_row(zd, {"kind": "pm_conflict", "work_id": a["work_id"],
                                      "field": a["field"], "trace": a["from"], "github": a["to"]}, root)
            else:
                trace.append_row(zd, {"kind": "pm_field_changed", "work_id": a["work_id"],
                                      "field": a["field"], "value": a["to"]}, root)
    finally:
        trace.release_lock(lp)
    for a in actions:
        tag = "CONFLICT (recorded, not overwritten)" if a.get("conflict") else "imported"
        print("  %s: %s %s %s -> %s" % (tag, a["work_id"], a["field"], a["from"], a["to"]))
    imp = sum(1 for a in actions if not a.get("conflict"))
    con = len(actions) - imp
    print("pm-pull: imported %d PM edit(s); %d conflict(s) recorded" % (imp, con))
    return 0


def cmd_pm_mirror(args):
    """Mirror the board to vault/<slug>/backlog.md so GitHub, the trace and the vault stay in
    sync (the trace is the source of truth; this is a generated view). [L13 multi-way]"""
    zd, root = _resolve(args)
    slug = _slug(zd) or os.path.basename(root)
    b = _board(zd, root)
    out = ["# Backlog — %s" % slug, "",
           "_Generated from the Zaude trace (source of truth). Do not hand-edit._", "",
           "## Intake (Ziad's column)"]
    out += ["- **%s** %s" % (it["id"], it["title"]) for it in b["intake"]] or ["- _(empty)_"]
    out += ["", "## Backlog"]
    for wid, i in b["items"].items():
        if i["type"] == "feature":
            out.append("- **[Feature] %s** `%s` _<%s>_" % (i["title"], wid, i.get("status")))
            if i.get("story"):
                out.append("  - %s" % i["story"])
            for cw, ci in b["items"].items():
                if ci.get("parent") == wid:
                    out.append("    - [%s] `%s` %s" % (ci["type"], cw, ci["title"]))
    vd = os.path.join(root, "vault", slug)
    os.makedirs(os.path.join(vd, "memory"), exist_ok=True)
    bp = os.path.join(vd, "backlog.md")
    with open(bp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    # ALSO sync a managed pointer into the project's memory index (GitHub↔trace↔vault↔memory)
    feats = [i for i in b["items"].values() if i["type"] == "feature"]
    entry = {"id": "backlog-state", "type": "project", "title": "%s backlog" % slug,
             "summary": "%d intake idea(s), %d feature(s); states: %s" % (
                 len(b["intake"]), len(feats),
                 ",".join(sorted({i.get("status") for i in feats})) or "-"),
             "source": "zaude-trace"}
    mi = os.path.join(vd, "memory", "memory-index.jsonl")
    kept = []
    try:
        with open(mi, "r", encoding="utf-8") as f:
            kept = [l for l in f if l.strip() and json.loads(l).get("id") != "backlog-state"]
    except Exception:
        pass
    with open(mi, "w", encoding="utf-8") as f:
        f.writelines(kept + [json.dumps(entry) + "\n"])
    print("mirrored board -> %s (+ memory index)" % os.path.relpath(bp, root))
    return 0


def cmd_version(args):
    home = os.path.expanduser("~")
    vdir = os.path.join(home, ".zaude", "kernel", "versions")
    versions = sorted(os.listdir(vdir)) if os.path.isdir(vdir) else []
    wired = os.path.isfile(os.path.join(home, ".zaude", "installed.json"))
    print("zaude kernel %s | installed: %s | wired into ~/.claude: %s"
          % (_kernel_version(), ",".join(versions) or "-", "yes" if wired else "no"))
    return 0


def cmd_package(args):
    """Assemble a clean, portable dist (no secrets) to ship to another PC / push to git. [DIST]"""
    from lib import dist
    try:
        r = dist.package(args.out)
    except ValueError as e:
        sys.stderr.write("package refused: %s\n" % e); return 1
    print("packaged %d files -> %s" % (r["files"], r["out_dir"]))
    print("  push to a git repo, or copy the folder to the other PC and run install.sh / install.ps1")
    return 0


def _git(args_list, token=None, cwd=None):
    import subprocess
    pre = ["git"]
    if token:
        pre += ["-c", "http.extraHeader=Authorization: Bearer " + token]  # ephemeral, not persisted
    return subprocess.run(pre + args_list, cwd=cwd, capture_output=True, text=True)


def cmd_update(args):
    """Update the kernel from a source (git URL or local dist path): pull new versions, bump CURRENT,
    regenerate, and re-wire ~/.claude if previously installed. Preserves secrets/state. [DIST]"""
    import argparse as _ap
    from lib import dist, generator
    home = os.path.expanduser("~")
    src = args.source
    if src.startswith("http"):
        # reject credential-bearing URLs — they'd persist a token in .src/.git/config [codex-HIGH]
        netloc = src.split("://", 1)[-1].split("/", 1)[0]
        if "@" in netloc:
            sys.stderr.write("refused: pass the URL WITHOUT embedded credentials; the token is read "
                             "from ~/.zaude/secrets.\n"); return 3
    if src.startswith("http") or src.startswith("git@"):
        srcdir = os.path.join(home, ".zaude", ".src")
        token = None
        if "github.com" in src:
            try:
                with open(os.path.join(home, ".zaude", "secrets", "github-pat"), "r", encoding="utf-8") as f:
                    token = f.read().strip()
            except Exception:
                token = None
        if os.path.isdir(os.path.join(srcdir, ".git")):
            r = _git(["-C", srcdir, "pull", "--ff-only"], token=token)
        else:
            import shutil as _sh
            _sh.rmtree(srcdir, ignore_errors=True)
            r = _git(["clone", "--depth", "1", src, srcdir], token=token)
        if r.returncode != 0:
            sys.stderr.write("update: git failed: %s\n" % (r.stderr or "")[-200:]); return 1
        copy_from = srcdir
    else:
        copy_from = os.path.abspath(os.path.expanduser(src))
        if not os.path.isdir(copy_from):
            sys.stderr.write("update: source not found: %s\n" % copy_from); return 1
    # validate the source is a real Zaude dist BEFORE overwriting live code [codex-HIGH: atomicity]
    try:
        src_cur = open(os.path.join(copy_from, "kernel", "CURRENT"), encoding="utf-8").read().strip()
    except Exception:
        src_cur = None
    if not (src_cur and os.path.isfile(os.path.join(copy_from, "bin", "zaude.py"))
            and os.path.isfile(os.path.join(copy_from, "kernel", "versions", src_cur, "cli.py"))):
        sys.stderr.write("refused: source isn't a valid Zaude dist (missing bin/zaude.py or "
                         "kernel/versions/<CURRENT>/cli.py) — not overwriting.\n"); return 3
    old = _kernel_version()
    # snapshot the live framework before overwriting, so a bad update is reversible
    import shutil as _sh
    snap = os.path.join(home, ".zaude", "restore-points", "pre-update-" + (old or "x"))
    for sub in ("bin", "policy", "kernel"):
        s = os.path.join(home, ".zaude", sub)
        if os.path.isdir(s):
            _sh.copytree(s, os.path.join(snap, sub), dirs_exist_ok=True)
    for sub in ("bin", "policy", "kernel"):
        s = os.path.join(copy_from, sub)
        if os.path.isdir(s):
            dst = os.path.join(home, ".zaude", sub)
            os.makedirs(dst, exist_ok=True)
            dist._copy_clean(s, dst)
    new = _kernel_version()
    generator.generate()
    rewired = False
    if os.path.isfile(os.path.join(home, ".zaude", "installed.json")):
        inst = _load_json(os.path.join(home, ".zaude", "installed.json"), {})
        cmd_install(_ap.Namespace(yes=True, force=True, prefix=inst.get("prefix", "z"), tag="update"))
        rewired = True
    print("updated kernel %s -> %s | regenerated%s"
          % (old, new, " + re-wired ~/.claude" if rewired else " (run `install --yes` to wire)"))
    return 0


def cmd_trace_verify(args):
    """Validate the signed trace: hash-chain + HMAC integrity + legal state replay. [L12]"""
    zd, root = _resolve(args)
    try:
        rows = trace.read_trace(zd, root, verify=True)
        cur = st.project_state(rows)
    except (trace.TraceCorrupt, trace.TraceForged, st.StateForged) as e:
        sys.stderr.write("TRACE INVALID: %s\n" % e); return 5
    print("trace OK: %d rows, chain + MAC verified, state replay valid -> %s" % (len(rows), cur))
    return 0


def cmd_gen(args):
    """Generate slash-commands + agents + the hook block from policy.json into the STAGING dir.
    Never touches live ~/.claude. [L6]"""
    from lib import generator
    r = generator.generate()
    print("generated -> %s" % r["out_dir"])
    print("  %d commands, %d agents, %d files (policy_sha=%s)"
          % (r["commands"], r["agents"], r["files"], r["policy_sha"]))
    print("  review the staged files, then `zaude install --yes` to wire them into ~/.claude.")
    return 0


def cmd_gen_status(args):
    from lib import generator
    home = os.path.expanduser("~")
    man = os.path.join(home, ".zaude", "generated", "manifest.json")
    m = _load_json(man, None)
    if m is None:
        print("not generated yet — run `zaude gen`."); return 1
    cur = generator._sha(generator.load_policy())
    drift = cur != m.get("policy_sha")
    print("staged files: %d | policy_sha staged=%s current=%s | %s"
          % (len(m.get("files", [])), m.get("policy_sha"), cur,
             "DRIFT — re-run `zaude gen`" if drift else "up to date"))
    return 1 if drift else 0


def _snapshot_claude(tag):
    import shutil
    home = os.path.expanduser("~")
    rp = os.path.join(home, ".zaude", "restore-points", tag)
    os.makedirs(rp, exist_ok=True)
    for sub in ("agents", "commands"):
        src = os.path.join(home, ".claude", sub)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(rp, "claude-" + sub), dirs_exist_ok=True)
    sj = os.path.join(home, ".claude", "settings.json")
    if os.path.isfile(sj):
        shutil.copyfile(sj, os.path.join(rp, "settings.json"))
    return rp


def _strict_json(path):
    """Load JSON, raising on a parse error. NEVER silently default — defaulting to {} on a parse
    error would let install WIPE existing settings/hooks. [codex]"""
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_install(args):
    """Wire the staged commands/agents/hook into the LIVE ~/.claude (snapshots first). MODIFIES the
    framework Deen uses daily — guarded by --yes. Commands install under a prefix (default 'z') so
    they don't clobber the existing /start /ship; only Zaude-owned files are overwritten (else
    --force). The hook is fail-open + per-project mode. Writes ~/.zaude/installed.json for a precise
    uninstall."""
    import shutil
    from lib import generator
    home = os.path.expanduser("~")
    gen = os.path.join(home, ".zaude", "generated")
    prefix = (args.prefix or "").strip()
    if not generator._NAME_RE.match(prefix):
        sys.stderr.write("refused: --prefix must be a non-empty safe token [A-Za-z0-9_-]\n"); return 3
    cmd_src, agent_src = os.path.join(gen, "commands"), os.path.join(gen, "agents")
    hbpath = os.path.join(gen, "hook-block.json")
    if not (os.path.isdir(cmd_src) and os.path.isfile(hbpath)):
        sys.stderr.write("refused: nothing staged — run `zaude gen` first.\n"); return 3
    try:
        hook_block = _strict_json(hbpath)
        assert isinstance(hook_block, dict) and hook_block.get("hooks")
    except Exception as e:
        sys.stderr.write("refused: staged hook-block.json invalid (%s)\n" % e); return 3
    cmds = sorted(f for f in os.listdir(cmd_src) if f.endswith(".md"))
    agents = sorted(f for f in os.listdir(agent_src) if f.endswith(".md")) if os.path.isdir(agent_src) else []
    cdst, adst = os.path.join(home, ".claude", "commands"), os.path.join(home, ".claude", "agents")

    def owned(p):
        try:
            return generator.MARKER in open(p, encoding="utf-8").read()
        except Exception:
            return False
    collisions = [os.path.relpath(os.path.join(cdst, prefix + fn), home) for fn in cmds
                  if os.path.exists(os.path.join(cdst, prefix + fn)) and not owned(os.path.join(cdst, prefix + fn))]
    collisions += [os.path.relpath(os.path.join(adst, fn), home) for fn in agents
                   if os.path.exists(os.path.join(adst, fn)) and not owned(os.path.join(adst, fn))]
    # strict settings load — a parse error ABORTS (never wipe his hooks)
    sjp = os.path.join(home, ".claude", "settings.json")
    try:
        sj = _strict_json(sjp)
    except Exception as e:
        sys.stderr.write("refused: ~/.claude/settings.json is not valid JSON (%s) — fix it first; "
                         "install will not risk your hooks.\n" % e); return 3
    sj = sj if sj is not None else {}
    pre = sj.get("hooks", {}).get("PreToolUse")
    if pre is not None and not isinstance(pre, list):
        sys.stderr.write("refused: settings.json hooks.PreToolUse is not a list.\n"); return 3

    if not getattr(args, "yes", False):
        print("INSTALL PLAN (dry-run — re-run with --yes):")
        print("  snapshot ~/.claude first")
        print("  + %d slash commands -> ~/.claude/commands/%s<name>.md" % (len(cmds), prefix))
        print("  + %d capability agents -> ~/.claude/agents/" % len(agents))
        print("  + 1 fail-open PreToolUse hook -> settings.json (per-project shadow/enforce)")
        if collisions:
            print("  !! %d NON-Zaude files would be overwritten (need --force):" % len(collisions))
            for c in collisions[:8]:
                print("       " + c)
        print("  reversible with `zaude uninstall` (manifest-driven).")
        return 2
    if collisions and not getattr(args, "force", False):
        sys.stderr.write("refused: %d non-Zaude files would be overwritten; re-run with --force.\n" % len(collisions))
        return 3

    rp = _snapshot_claude("install-" + (args.tag or "manual"))
    os.makedirs(cdst, exist_ok=True); os.makedirs(adst, exist_ok=True)
    installed = {"prefix": prefix, "commands": [], "agents": [], "hook": hook_block}
    for fn in cmds:
        t = os.path.join(cdst, prefix + fn); shutil.copyfile(os.path.join(cmd_src, fn), t)
        installed["commands"].append(t)
    for fn in agents:
        t = os.path.join(adst, fn); shutil.copyfile(os.path.join(agent_src, fn), t)
        installed["agents"].append(t)
    pre = sj.setdefault("hooks", {}).setdefault("PreToolUse", [])
    if hook_block not in pre:   # exact-object idempotence — never substring-matches another hook
        pre.append(hook_block)
    trace.write_json_atomic(sjp, sj)
    trace.write_json_atomic(os.path.join(home, ".zaude", "installed.json"), installed)
    print("installed %d commands (prefix '%s') + %d agents + hook. snapshot: %s"
          % (len(cmds), prefix, len(agents), rp))
    print("NEXT: onboard a pilot in SHADOW mode, watch hooklog.jsonl, then enforce.")
    return 0


def cmd_uninstall(args):
    """Reverse install using the recorded manifest (~/.zaude/installed.json): removes EXACTLY the
    files we wrote + the EXACT hook entry. Snapshots first. [codex: manifest-driven, exact match]"""
    home = os.path.expanduser("~")
    inst = _load_json(os.path.join(home, ".zaude", "installed.json"), None)
    if inst is None:
        sys.stderr.write("nothing recorded as installed (~/.zaude/installed.json missing).\n"); return 1
    rp = _snapshot_claude("uninstall-" + (args.tag or "manual"))
    removed = 0
    for t in inst.get("commands", []) + inst.get("agents", []):
        if os.path.isfile(t):
            os.remove(t); removed += 1
    sjp = os.path.join(home, ".claude", "settings.json")
    try:
        sj = _strict_json(sjp)
        parse_ok = True
    except Exception:
        sj, parse_ok = None, False
    if sj and isinstance(sj.get("hooks", {}).get("PreToolUse"), list):
        hb = inst.get("hook")
        sj["hooks"]["PreToolUse"] = [e for e in sj["hooks"]["PreToolUse"] if e != hb]
        trace.write_json_atomic(sjp, sj)
    if not parse_ok and os.path.isfile(sjp):
        # couldn't parse settings -> couldn't remove the hook -> KEEP the manifest so a retry works
        sys.stderr.write("note: settings.json could not be parsed; the hook was left in place and "
                         "the manifest kept — fix settings.json and re-run `uninstall`.\n")
        print("removed %d files; hook NOT removed (see note). snapshot: %s" % (removed, rp))
        return 1
    os.remove(os.path.join(home, ".zaude", "installed.json"))
    print("uninstalled %d files + the Zaude hook. snapshot: %s" % (removed, rp))
    return 0


# Next legal lifecycle command for each state — lets a driver loop autonomously (run /next, do it,
# repeat) to DoD without hardcoding the sequence (finding #1). [L13/autonomous]
_NEXT_COMMAND = {
    "Intake": "/clarify", "Clarified": "/prioritize", "Prioritized": "/plan", "Planned": "/design",
    "Designed": "/classify-risk", "RiskClassified": "/approve", "Approved": "/implement",
    "Implemented": "/test", "Tested": "/review", "Reviewed": "/verify", "Verified": "/shippable",
    "Shippable": "/ship", "Released": "/close", "Closed": None,
}


def cmd_next(args):
    """Autonomous helper (finding #1): print the next lifecycle command for the current state, or
    DoD when done — so a driver can loop until DoD without a hardcoded sequence. Read-only; exit 0.
    (Low/medium-risk work may instead collapse the chain via /fast + /fast-ship.)"""
    zd, root = _resolve(args)
    proj = _projection_out(zd, root)
    cur = proj["current_state"]
    done = cur in ("Released", "Closed")
    nxt = _NEXT_COMMAND.get(cur)
    out = {"current_state": cur, "next_command": nxt, "dod_reached": done,
           "risk_tier": proj.get("risk_tier")}
    if getattr(args, "as_json", False):
        print(json.dumps(out))
        return 0
    if done:
        print("DoD path: state=%s — run /dod to confirm done-with-evidence%s."
              % (cur, "" if cur == "Closed" else ", then /close"))
    else:
        print("next: %s   (state=%s, risk=%s)" % (nxt, cur, proj.get("risk_tier") or "unclassified"))
    return 0


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _redact_url(u):
    """Strip embedded credentials (user:pass@ / x-access-token:<tok>@) from a git URL before it is
    ever logged. Also redacts any such pattern that leaks into git stderr. [codex-HIGH]"""
    import re as _re
    try:
        return _re.sub(r"(://)[^/@\s]+@", r"\1<redacted>@", u or "")
    except Exception:
        return "<remote>"


def cmd_vault_push(args):
    """#2 — sync the project vault to a SHARED GitHub repo. The vault gets its OWN git repo under
    vault/ (independent of the project code repo) so it can push to a dedicated vault remote, which
    matches the operator's existing dedicated-vault model. Best-effort + offline-safe: no remote
    configured -> advisory; any git failure -> reported, never crashes the kernel. The remote is
    persisted to .zaude/vault.json so subsequent pushes need no flag."""
    zd, root = _resolve(args)
    vault_dir = os.path.join(root, "vault")
    if not os.path.isdir(vault_dir):
        sys.stderr.write("vault: no vault/ dir (run /onboard first)\n")
        return 0
    cfg_path = os.path.join(zd, "vault.json")
    cfg = _read_json(cfg_path) or {}
    if not isinstance(cfg, dict):              # a non-object vault.json must not crash .get() [codex]
        cfg = {}
    remote = getattr(args, "remote", None) or cfg.get("remote")
    if not remote:
        print("vault: no remote configured — set one with: zaude vault-push --remote <git-url>")
        return 0
    branch = (cfg.get("branch") or "main")
    safe_remote = _redact_url(remote)   # the ONLY form of the remote that is ever printed

    def _git(*a, timeout=60):
        return subprocess.run(["git", "-C", vault_dir] + list(a),
                              capture_output=True, text=True, timeout=timeout)
    # EVERYTHING below is best-effort: any failure (incl. the config/gitignore writes) is reported
    # with a REDACTED remote and exits 0 — vault-push must NEVER crash the kernel. [codex]
    try:
        cfg["remote"] = remote
        trace.write_json_atomic(cfg_path, cfg)
        # Keep the PARENT project repo from tracking the nested vault git repo (git warns on
        # embedded repos / could stage a stray gitlink). Ignore the whole vault/ in the parent.
        gi = os.path.join(root, ".gitignore")
        body = ""
        if os.path.exists(gi):
            with open(gi, "r", encoding="utf-8") as f:
                body = f.read()
        if "vault/" not in body.split():
            with open(gi, "a", encoding="utf-8") as f:
                f.write(("\n" if body and not body.endswith("\n") else "") + "vault/\n")
        if not os.path.isdir(os.path.join(vault_dir, ".git")):
            _git("init", "-q")
            _git("checkout", "-q", "-B", branch)
        _git("remote", "remove", "origin")             # idempotent: reset the remote each push
        r = _git("remote", "add", "origin", remote)
        if r.returncode != 0:
            sys.stderr.write("vault: bad remote (%s)\n" % _redact_url((r.stderr or "").strip())[:160])
            return 0
        _git("add", "-A")
        _git("-c", "user.email=zaude@local", "-c", "user.name=zaude",
             "commit", "-q", "-m", "vault sync")        # no-op (rc!=0) when nothing changed — fine
        p = _git("push", "-u", "origin", "HEAD:%s" % branch, timeout=120)
        if p.returncode != 0:
            sys.stderr.write("vault: push failed (best-effort) — %s\n"
                             % _redact_url((p.stderr or "").strip())[:200])
            return 0
        print("vault: pushed %s -> %s (%s)"
              % (os.path.relpath(vault_dir, root), safe_remote, branch))
        return 0
    except Exception as e:
        sys.stderr.write("vault: push error (best-effort) — %s\n" % _redact_url(str(e))[:160])
        return 0


_CI_WORKFLOW = """\
# Auto-generated by host-once-zaude (finding #6). Runner: %(runs_on)s.
name: zaude-ci
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: %(runs_on)s
    steps:
      - uses: actions/checkout@v4
      - name: Run Zaude kernel tests
        run: |
          cd kernel/versions/0.2.0 && python -m unittest discover -s tests
"""

_RUNNER_SETUP = """\
#!/usr/bin/env bash
# Auto-generated by host-once-zaude (finding #6) — set up a SELF-HOSTED GitHub Actions runner on
# this VPS. SECURITY: only use a self-hosted runner with a PRIVATE repo — a fork PR on a public
# repo can run untrusted code on this machine (GitHub's own guidance).
#
# Provide the time-limited registration token (expires ~1h) from:
#   Repo > Settings > Actions > Runners > New self-hosted runner.
# Pass it via the GITHUB_RUNNER_TOKEN env var (preferred — not in shell history) or as $1.
set -euo pipefail   # NOTE: no `set -x` — never echo the token
REPO_URL="%(repo_url)s"
RUNNER_TOKEN="${GITHUB_RUNNER_TOKEN:-${1:-}}"
[ -n "${RUNNER_TOKEN}" ] || { echo "usage: GITHUB_RUNNER_TOKEN=<token> ./runner-setup.sh   (or pass as \\$1)"; exit 2; }
# Discover the latest runner release at runtime (do not ship a stale pinned version).
RUNNER_VERSION="${RUNNER_VERSION:-$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \\
  | grep -oE '"tag_name": *"v[0-9.]+"' | grep -oE '[0-9.]+' | head -1)}"
[ -n "${RUNNER_VERSION}" ] || { echo "could not discover runner version; set RUNNER_VERSION=x.y.z"; exit 1; }
mkdir -p ~/actions-runner && cd ~/actions-runner
TARBALL="actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
curl -fsSL -o "${TARBALL}" \\
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"
tar xzf "${TARBALL}"
./config.sh --url "${REPO_URL}" --token "${RUNNER_TOKEN}" --unattended --labels self-hosted
sudo ./svc.sh install && sudo ./svc.sh start
echo "self-hosted runner v${RUNNER_VERSION} installed + started for ${REPO_URL}"
"""


def cmd_runner(args):
    """#6 — emit CI for the project: a GitHub Actions workflow using either the default
    GitHub-hosted runner (--mode github) or a self-hosted runner on a VPS (--mode self-hosted),
    plus, for self-hosted, a runner-install script to run ON the VPS. Generates artifacts only
    (Zaude never SSHes anywhere) — the operator runs the script. Always exits 0."""
    zd, root = _resolve(args)
    mode = getattr(args, "mode", "github") or "github"
    runs_on = "self-hosted" if mode == "self-hosted" else "ubuntu-latest"
    try:                                   # emit-only; any FS error reports + exits 0 (never crash)
        wf_dir = os.path.join(root, ".github", "workflows")
        os.makedirs(wf_dir, exist_ok=True)
        wf_path = os.path.join(wf_dir, "zaude-ci.yml")
        with open(wf_path, "w", encoding="utf-8") as f:
            f.write(_CI_WORKFLOW % {"runs_on": runs_on})
        written = [os.path.relpath(wf_path, root)]
        if mode == "self-hosted":
            repo_url = getattr(args, "repo_url", None) or "https://github.com/<owner>/<repo>"
            setup_path = os.path.join(root, ".github", "runner-setup.sh")
            with open(setup_path, "w", encoding="utf-8") as f:
                f.write(_RUNNER_SETUP % {"repo_url": repo_url})
            try:
                os.chmod(setup_path, 0o755)
            except Exception:
                pass
            written.append(os.path.relpath(setup_path, root))
    except Exception as e:
        sys.stderr.write("runner: emit failed (%s)\n" % str(e)[:120])
        return 0
    print("runner: emitted %s (runs-on: %s)" % (", ".join(written), runs_on))
    if mode == "self-hosted":
        print("SECURITY: use a self-hosted runner ONLY with a PRIVATE repo (a fork PR on a public "
              "repo can run untrusted code on the VPS).")
        print("next: on the VPS run  GITHUB_RUNNER_TOKEN=<token> bash .github/runner-setup.sh  "
              "(token from Repo > Settings > Actions > Runners > New self-hosted runner; ~1h TTL).")
    return 0


def cmd_persona(args):
    """OPERATOR-LEARNING persona — the distilled 'decide as the operator would' profile that
    autonomous mode loads FIRST. Read by default; light-write via --observe/--promote/--forget.
    Always exits 0 (advisory; never gates). [operator-learning layer]"""
    zd, root = _resolve(args)
    if getattr(args, "observe", None):
        s = persona.observe(zd, getattr(args, "kind", "preference") or "preference",
                            args.observe, source="operator")
        print("persona: signal recorded (%s)" % s["kind"])
        return 0
    if getattr(args, "promote", None):
        b = persona.promote(zd, getattr(args, "category", "preference") or "preference",
                            args.promote, source="operator")
        reinf = int(b.get("reinforcement", 1))
        if b.get("drift"):
            print("persona: ! possible preference drift — conflicts with: %s"
                  % "; ".join(b.get("conflicts", [])))
        print("persona: belief %s — %s (x%d)"
              % (b.get("id"), "CONFIRMED" if reinf >= persona.PROMOTE_MIN else "tentative", reinf))
        return 0
    if getattr(args, "forget", None):
        ok = persona.forget(zd, args.forget)
        print("persona: %s %s" % ("forgot" if ok else "no such belief", args.forget))
        return 0
    if getattr(args, "as_json", False):
        print(json.dumps({"brief": persona.brief(zd), "beliefs": persona.beliefs(zd)}))
        return 0
    b = persona.brief(zd)
    print(b if b else "persona: still learning — no confirmed beliefs yet. Record one with "
          "`zaude persona --promote \"...\" --category preference|rule|risk_posture`.")
    return 0


def cmd_remember(args):
    """COLLECTIVE MEMORY — append a lesson/fact/decision (redacted, operator-private). Exit 0."""
    zd, root = _resolve(args)
    tags = [t.strip() for t in (getattr(args, "tags", "") or "").split(",") if t.strip()]
    r = memory.remember(zd, args.text, tags=tags, source="operator")
    if r["text"].strip():
        print("remembered: %s%s" % (r["text"][:80], "…" if len(r["text"]) > 80 else ""))
    else:
        print("remember: empty — nothing stored")
    return 0


def cmd_recall(args):
    """COLLECTIVE MEMORY — retrieve the most relevant entries for a query (TF-IDF). Read-only. Exit 0."""
    zd, root = _resolve(args)
    try:
        k = max(1, int(getattr(args, "k", 5) or 5))
    except Exception:
        k = 5
    hits = memory.recall(zd, args.query, k=k)
    if getattr(args, "as_json", False):
        print(json.dumps(hits))
        return 0
    if not hits:
        print("recall: nothing relevant (%d entries stored)." % memory.count(zd))
        return 0
    for h in hits:
        tg = ("  [%s]" % ",".join(h["tags"])) if h.get("tags") else ""
        print("- (%.3f) %s%s" % (h["score"], h["text"][:120], tg))
    return 0


def cmd_route(args):
    """INTENT DETECTION — given a natural-language request, return the best-matching Zaude command
    + a safety mode (auto/propose/confirm/ambiguous). Read-only: it SUGGESTS; the routed command
    records its own transition when actually run. The driver reads `mode` to decide whether to
    auto-run (safe), confirm (destructive), or show options (ambiguous). Always exits 0."""
    zd, root = _resolve(args)
    try:
        cur = _projection_out(zd, root).get("current_state")
    except Exception:
        cur = None
    res = router.route(args.text, cur)
    if getattr(args, "as_json", False):
        print(json.dumps(res))
        return 0
    if not res.get("command"):
        print("route: no clear command — try /status or /next, or rephrase.")
        return 0
    print("route: /%s  (mode=%s, confidence=%.2f)" % (res["command"], res["mode"], res["confidence"]))
    if res.get("blocked_by"):
        print("  blocked: " + "; ".join(res["blocked_by"]))
    if res.get("alternates"):
        print("  alternates: " + ", ".join("/%s(%.2f)" % (a["command"], a["confidence"])
                                           for a in res["alternates"]))
    if res["mode"] == "confirm":
        print("  ! destructive — confirm before running.")
    elif res["mode"] == "ambiguous":
        print("  ambiguous — pick an alternate or rephrase.")
    return 0


def cmd_status(args):
    zd, root = _resolve(args)
    print(json.dumps(_projection_out(zd, root), indent=2))
    return 0


def cmd_repair(args):
    zd, root = _resolve(args)
    try:
        rows = trace.read_trace(zd, root, verify=True)
        cur = st.project_state(rows)
    except trace.TraceCorrupt as e:
        sys.stderr.write("HALT: %s — trace corrupt; manual recovery.\n" % e); return 5
    except trace.TraceForged as e:
        sys.stderr.write("HALT: %s — trace TAMPERED; manual review (the chain/MAC failed).\n" % e); return 5
    except st.StateForged as e:
        sys.stderr.write("HALT: %s — forged transition; manual review.\n" % e); return 5
    _refresh_state(zd, root)
    print("repaired: state.json rebuilt from %d rows -> %s" % (len(rows), cur))
    return 0


def cmd_doctor(args):
    zd, root = _resolve(args)
    issues = []
    try:
        rows = trace.read_trace(zd, root, verify=True)
        st.reduce(rows)
    except Exception as e:
        issues.append("trace: %s" % e)
    if _kernel_version() != _project_kernel_version(zd):
        issues.append("kernel_version drift: project=%s current=%s"
                      % (_project_kernel_version(zd), _kernel_version()))
    # codex is best-effort: mere ABSENCE is advisory (never an issue / never flips the exit code),
    # but a MISCONFIGURED token (symlink / wrong location) IS a real issue worth flagging.
    if codex.token_misconfigured():
        issues.append("codex token ~/.zaude/secrets/codex is unsafe (symlink/wrong location)")
    cx = codex.probe()
    print("DOCTOR: codex %s (%s)%s" % (cx["status"], cx.get("detail", ""),
          "" if cx["status"] == codex.READY else " — reviews continue without it"))
    # required agents: ADVISORY only (never an issue / never flips the exit code — a fresh machine
    # legitimately has none, and installing them is the operator's job). Visibility for #4.1.
    ag = agents.check(root)
    if ag["missing"]:
        print("DOCTOR: agents %d/%d required present — MISSING: %s (install as "
              "~/.claude/agents/<name>.md; commands that invoke them will degrade)"
              % (len(ag["present"]), len(ag["required"]), ", ".join(ag["missing"])))
    else:
        print("DOCTOR: agents %d/%d required present." % (len(ag["present"]), len(ag["required"])))
    # PM board staleness — ADVISORY only (offline-safe; pushing is the operator's /pm-sync). #3.1
    try:
        n_stale = _pm_unsynced(trace.read_trace(zd, root, verify=True))
        if n_stale:
            print("DOCTOR: PM board STALE — %d change(s) since last /pm-sync (run /pm-sync)." % n_stale)
    except Exception:
        pass
    if issues:
        print("DOCTOR: %d issue(s):" % len(issues))
        for i in issues:
            print("  - " + i)
        return 1
    print("DOCTOR: ok")
    return 0


def cmd_agents(args):
    """Read-only required-agent presence report. Always exits 0 — advisory, like /codex (a missing
    agent is the operator's to install, never a kernel failure). [L7/agent-reliability #4.1]"""
    zd, root = _resolve(args)
    ag = agents.check(root)
    if getattr(args, "as_json", False):
        print(json.dumps(ag))
        return 0
    print("required agents: %d (%d total installed)" % (len(ag["required"]), ag["installed_total"]))
    print("  present: %s" % (", ".join(ag["present"]) or "(none)"))
    print("  MISSING: %s" % (", ".join(ag["missing"]) or "(none)"))
    if ag["missing"]:
        print("hint: install missing agents as ~/.claude/agents/<name>.md (or "
              "<project>/.claude/agents/). Zaude generates only its own capability agents; the "
              "review/build agents are installed separately.")
    return 0


def cmd_codex(args):
    """Read-only codex status (availability + token + retry window). Always exits 0 — it is the
    codex analog of /status & /doctor, not a gate. [L13/graceful-codex]"""
    zd, root = _resolve(args)
    d = codex.read_status(zd)
    if getattr(args, "probe", False) or not d.get("last_probe"):
        pr = codex.probe()
        d["last_probe"] = pr
        codex.write_status(zd, d)
    else:
        pr = d["last_probe"]
    retry = d.get("retry") or {}
    tok = ("configured" if codex.have_token() else
           ("MISCONFIGURED" if codex.token_misconfigured() else "none"))
    if getattr(args, "as_json", False):
        print(json.dumps({"status": pr.get("status"), "version": pr.get("version"),
                          "auth_source": pr.get("auth_source"), "detail": pr.get("detail"),
                          "token": tok, "retry": retry}))
        return 0
    print("codex: %s (%s)" % (pr.get("status"), pr.get("detail") or ""))
    print("token: %s" % tok)
    print("retry: %s" % ("blocked reason=%s retry_at=%s" % (retry.get("reason"), retry.get("retry_at"))
                         if retry.get("blocked") else "none"))
    if pr.get("status") != codex.READY:
        print("hint: run `codex login`, or drop a token at ~/.zaude/secrets/codex (or set "
              "ZAUDE_CODEX_TOKEN). Codex is best-effort — reviews proceed without it.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="zaude")
    p.add_argument("--path", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init"); sp.add_argument("--text", required=True)
    sp.add_argument("--mode", choices=("shadow", "enforce"), default="enforce")
    sp.add_argument("--force", action="store_true"); sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("clarify"); sp.add_argument("--acceptance", required=True)
    sp.set_defaults(fn=_simple("Intake", "Clarified", "/clarify", "requirements.json",
                    lambda a: [{"req_id": "REQ-1", "acceptance": a.acceptance}]))

    sp = sub.add_parser("prioritize"); sp.add_argument("--decision", required=True)
    sp.set_defaults(fn=_simple("Clarified", "Prioritized", "/prioritize", "priority.json",
                    lambda a: {"decision": a.decision}))

    sp = sub.add_parser("plan"); sp.add_argument("--steps", required=True)
    sp.set_defaults(fn=_simple("Prioritized", "Planned", "/plan", "plan.json",
                    lambda a: {"ordered_steps": a.steps.split(",")}))

    sp = sub.add_parser("design"); sp.add_argument("--approach", required=True)
    sp.add_argument("--decision", required=True)
    sp.set_defaults(fn=_simple("Planned", "Designed", "/design", "design.json",
                    lambda a: {"approach": a.approach, "decision_id": a.decision, "alternatives": []}))

    sp = sub.add_parser("classify-risk"); sp.add_argument("--tier", required=True)
    sp.set_defaults(fn=cmd_classify_risk)

    sp = sub.add_parser("fast"); sp.add_argument("--note", required=True)
    sp.add_argument("--tier", default="T1"); sp.set_defaults(fn=cmd_fast)

    sp = sub.add_parser("fast-ship"); sp.add_argument("--tested-cmd", dest="tested_cmd", default="tests")
    sp.add_argument("--tested-exit", dest="tested_exit", required=True)
    sp.add_argument("--deploy-id", dest="deploy_id", default="d1"); sp.set_defaults(fn=cmd_fast_ship)

    sp = sub.add_parser("approve"); sp.add_argument("--by", required=True)
    sp.add_argument("--scope", default="work")
    sp.set_defaults(fn=_simple("RiskClassified", "Approved", "/approve", "approval.json",
                    lambda a: {"by": a.by, "scope": a.scope}))

    sp = sub.add_parser("implement")
    sp.set_defaults(fn=_simple("Approved", "Implemented", "/implement", "impl.json",
                    lambda a: {"note": "implementation in progress"}))

    sp = sub.add_parser("test"); sp.add_argument("--cmd", required=True)
    sp.add_argument("--exit", type=int, required=True)
    sp.set_defaults(fn=_simple("Implemented", "Tested", "/test", "test-results.json",
                    lambda a: {"cmd": a.cmd, "exit": a.exit}))

    sp = sub.add_parser("review"); sp.add_argument("--summary", default="")
    sp.add_argument("--unresolved", default="0")
    sp.add_argument("--codex", choices=("auto", "on", "off", "never"), default="auto")
    sp.add_argument("--codex-verdict", dest="codex_verdict",
                    choices=("pass", "concerns", "fail"), default=None)
    sp.add_argument("--codex-summary", dest="codex_summary", default="")
    sp.add_argument("--codex-error", dest="codex_error", default=None,
                    help="codex's error output when it FAILED (quota/rate-limit/auth). Arms the "
                         "no-credit backoff so codex auto-resumes when the reset window passes.")
    sp.add_argument("--codex-retry-at", dest="codex_retry_at", default=None,
                    help="explicit retry time (epoch seconds or ISO-8601) for a codex no-credit "
                         "backoff; overrides any reset hint parsed from --codex-error.")
    sp.set_defaults(fn=cmd_review)

    sp = sub.add_parser("verify"); sp.add_argument("--built", default="ok")
    sp.add_argument("--health", default="ok"); sp.add_argument("--probe", default="ok")
    sp.set_defaults(fn=cmd_verify)

    sp = sub.add_parser("shippable")
    sp.set_defaults(fn=_simple("Verified", "Shippable", "/shippable", "shippable.json",
                    lambda a: {"all_gates": "green"}))

    sp = sub.add_parser("ship"); sp.add_argument("--deploy-id", default="d1")
    sp.add_argument("--rollback", default="revert"); sp.set_defaults(fn=cmd_ship)

    sp = sub.add_parser("close")
    sp.set_defaults(fn=_simple("Released", "Closed", "/close", "handoff.json",
                    lambda a: {"closed": True}))

    sp = sub.add_parser("waive"); sp.add_argument("--gate", required=True)
    sp.add_argument("--reason", required=True); sp.add_argument("--by", required=True)
    sp.set_defaults(fn=cmd_waive)

    sp = sub.add_parser("onboard"); sp.add_argument("--slug", required=True)
    sp.add_argument("--text", required=True); sp.add_argument("--stack", default="unknown")
    sp.add_argument("--mode", choices=("shadow", "enforce"), default="enforce")
    sp.set_defaults(fn=cmd_onboard)

    sp = sub.add_parser("pm-add"); sp.add_argument("--note", required=True)
    sp.set_defaults(fn=cmd_pm_add)

    sp = sub.add_parser("promote"); sp.add_argument("--intake", required=True)
    sp.add_argument("--title", required=True); sp.add_argument("--story", required=True)
    sp.add_argument("--ac", default=""); sp.add_argument("--tasks", default="")
    sp.add_argument("--bugs", default=""); sp.add_argument("--priority", default="P2")
    sp.add_argument("--risk", default="Medium"); sp.set_defaults(fn=cmd_promote)

    sp = sub.add_parser("pm-move"); sp.add_argument("--work-id", dest="work_id", required=True)
    sp.add_argument("--to", required=True); sp.set_defaults(fn=cmd_pm_move)

    sub.add_parser("board").set_defaults(fn=cmd_board)

    sp = sub.add_parser("pm-init"); sp.add_argument("--login", required=True)
    sp.add_argument("--repo", required=True)
    sp.add_argument("--title", default="Zaude — Product Backlog"); sp.set_defaults(fn=cmd_pm_init)

    sp = sub.add_parser("pm-sync"); sp.add_argument("--login", default=None)
    sp.add_argument("--repo", default=None); sp.add_argument("--title", default=None)
    sp.set_defaults(fn=cmd_pm_sync)

    sub.add_parser("pm-mirror").set_defaults(fn=cmd_pm_mirror)
    sub.add_parser("pm-pull").set_defaults(fn=cmd_pm_pull)

    sub.add_parser("dod").set_defaults(fn=cmd_dod)

    sp = sub.add_parser("persona")
    sp.add_argument("--observe", default=None)
    sp.add_argument("--kind", default="preference")
    sp.add_argument("--promote", default=None)
    sp.add_argument("--category", default="preference")
    sp.add_argument("--forget", default=None)
    sp.add_argument("--json", dest="as_json", action="store_true")
    sp.set_defaults(fn=cmd_persona)

    sp = sub.add_parser("next"); sp.add_argument("--json", dest="as_json", action="store_true")
    sp.set_defaults(fn=cmd_next)

    sp = sub.add_parser("vault-push"); sp.add_argument("--remote", default=None)
    sp.set_defaults(fn=cmd_vault_push)

    sp = sub.add_parser("runner"); sp.add_argument("--mode", choices=("github", "self-hosted"),
                                                   default="github")
    sp.add_argument("--repo-url", dest="repo_url", default=None); sp.set_defaults(fn=cmd_runner)

    sp = sub.add_parser("route"); sp.add_argument("text")
    sp.add_argument("--json", dest="as_json", action="store_true"); sp.set_defaults(fn=cmd_route)

    sp = sub.add_parser("remember"); sp.add_argument("text"); sp.add_argument("--tags", default="")
    sp.set_defaults(fn=cmd_remember)

    sp = sub.add_parser("recall"); sp.add_argument("query"); sp.add_argument("--k", default="5")
    sp.add_argument("--json", dest="as_json", action="store_true"); sp.set_defaults(fn=cmd_recall)

    sp = sub.add_parser("codex"); sp.add_argument("--probe", action="store_true")
    sp.add_argument("--json", dest="as_json", action="store_true"); sp.set_defaults(fn=cmd_codex)

    sp = sub.add_parser("agents"); sp.add_argument("--json", dest="as_json", action="store_true")
    sp.set_defaults(fn=cmd_agents)

    sub.add_parser("trace-verify").set_defaults(fn=cmd_trace_verify)
    sub.add_parser("version").set_defaults(fn=cmd_version)
    sp = sub.add_parser("package"); sp.add_argument("--out", required=True); sp.set_defaults(fn=cmd_package)
    sp = sub.add_parser("update"); sp.add_argument("--source", required=True); sp.set_defaults(fn=cmd_update)
    sub.add_parser("gen").set_defaults(fn=cmd_gen)
    sub.add_parser("gen-status").set_defaults(fn=cmd_gen_status)
    sp = sub.add_parser("install"); sp.add_argument("--yes", action="store_true")
    sp.add_argument("--force", action="store_true"); sp.add_argument("--prefix", default="z")
    sp.add_argument("--tag", default=None); sp.set_defaults(fn=cmd_install)
    sp = sub.add_parser("uninstall"); sp.add_argument("--prefix", default="z")
    sp.add_argument("--tag", default=None); sp.set_defaults(fn=cmd_uninstall)

    for name, fn in (("status", cmd_status), ("repair", cmd_repair), ("doctor", cmd_doctor)):
        sub.add_parser(name).set_defaults(fn=fn)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
