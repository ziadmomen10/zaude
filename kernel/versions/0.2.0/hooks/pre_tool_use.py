"""
pre_tool_use.py (v0.2.0) — the PreToolUse gate.

Precedence: kill switch -> not-onboarded -> shadow(log only) -> enforce(may deny). Corrupt OR
FORGED trace fails closed in enforce, allows in shadow. Decisions run over the single reducer
+ GateContext. [A1, B1, B2, D14]
"""
import os
import sys
import json
import time

_VROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _VROOT)


def _allow():
    sys.exit(0)


def _deny(reason):
    try:
        out = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    except Exception:
        # emitting the structured deny failed -> HARD fail-closed (exit 2 blocks a PreToolUse call
        # and surfaces stderr). A deny must NEVER degrade into an allow. [codex review HIGH]
        try:
            sys.stderr.write("Zaude blocked the edit (deny emit failed): %s\n" % reason)
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(2)
    sys.exit(0)


def _hooklog(zaude_dir, payload):
    try:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        fd = os.open(os.path.join(zaude_dir, "hooklog.jsonl"),
                     os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass


def _global_log(payload):
    """Best-effort log to a USER-GLOBAL file (~/.zaude/hooklog.jsonl), NOT the untrusted project
    .zaude/ — a broken marker means the project .zaude is exactly the surface we can't trust.
    Never raises, never affects the allow/deny decision. [codex co-plan #5]"""
    try:
        d = os.path.join(os.path.expanduser("~"), ".zaude")
        os.makedirs(d, exist_ok=True)
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        fd = os.open(os.path.join(d, "hooklog.jsonl"), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass


def main():
    t0 = time.time()
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        _allow()

    try:
        from lib import paths, gates, trace, state as st, board
    except Exception:
        _allow()

    # Resolution itself is in the broad fail-open catch (a TOTAL resolution failure -> allow, the
    # pre-existing contract). But the none/broken/onboarded DECISION is handled OUTSIDE it so the
    # fail-CLOSED broken-marker branch can never be swallowed back into an allow. [codex review HIGH]
    try:
        if paths.kill_switch_active():
            _allow()
        cwd = data.get("cwd") or os.getcwd()
        res = paths.resolve(cwd)
    except Exception:
        _allow()

    status = res.get("status") if isinstance(res, dict) else "none"
    if status == "none":
        _allow()
    if status == "broken":
        # An onboarded project whose .zaude/project.json is unreadable / empty / garbled / a dangling
        # symlink. Its enforcement_mode lives INSIDE that corrupt file, so we cannot prove it was
        # shadow -> fail CLOSED (symmetric with a corrupt trace). Log GLOBALLY (the project .zaude is
        # the untrusted surface). Kill switch (ZAUDE_DISABLE=1 / ~/.zaude/disabled) escapes.
        broken_root = res.get("broken_root") or (data.get("cwd") or os.getcwd())
        _global_log({"ts": time.time(), "hook": "PreToolUse", "event": "marker_broken",
                     "project_root": broken_root, "reason": res.get("reason"),
                     "tool": data.get("tool_name", ""),
                     "duration_ms": int((time.time() - t0) * 1000)})
        _deny("Zaude project marker is missing or corrupt at %s%s.zaude%sproject.json (%s). "
              "Fail-closed by design. To recover: re-onboard (`zaude onboard`) or restore the "
              "file; if this is NOT a Zaude project, delete or rename that file; or set "
              "ZAUDE_DISABLE=1 to bypass." % (broken_root, os.sep, os.sep, res.get("reason")))
    proj = res["ctx"]

    zaude_dir = proj["zaude_dir"]
    root = proj["root"]
    mode = proj["enforcement_mode"]
    tool = data.get("tool_name", "")
    tinput = data.get("tool_input", {}) or {}
    if not isinstance(tinput, dict):
        tinput = {}
    target = tinput.get("file_path") or tinput.get("notebook_path") or ""

    # P4: gate against the ACTIVE work item's single-track sub-trace if one is set, else the root
    # trace (today's path). active_item_dir() is TOTAL — None on ANY problem (no items dir, no active
    # item, set-but-missing dir, error) -> root projection = byte-identical to today. The PROJECTION
    # comes from the active item; gates.evaluate still receives the ROOT zaude_dir (so protect_zaude /
    # _under still protect ALL of .zaude/, including items/). A forged ACTIVE sub-trace raises
    # TraceForged here exactly like a forged root -> fail-closed in enforce. [P4 Approach A]
    gate_dir = board.active_item_dir(zaude_dir) or zaude_dir
    try:
        rows = trace.read_trace(gate_dir, root, verify=True)
        proj_state = st.reduce(rows)
        decision, reason, gate = gates.evaluate(proj_state, tool, tinput, zaude_dir)
        cur = proj_state.get("current_state")
    except (trace.TraceCorrupt, trace.TraceForged, st.StateForged) as e:
        _hooklog(zaude_dir, {"ts": time.time(), "hook": "PreToolUse", "mode": mode,
                             "decision": "deny" if mode == "enforce" else "would-deny",
                             "reason": type(e).__name__,
                             "duration_ms": int((time.time() - t0) * 1000)})
        if mode == "enforce":
            _deny("Zaude trace is corrupt or forged (%s). `zaude repair`/recover before "
                  "editing. Fail-closed by design." % e)
        _allow()
    except Exception:
        if mode == "enforce":
            _deny("Zaude gate error. Inspect .zaude or set ZAUDE_DISABLE=1 to bypass.")
        _allow()

    _hooklog(zaude_dir, {
        "ts": time.time(), "hook": "PreToolUse", "project_root": root, "mode": mode,
        "tool": tool, "target": target, "state": cur, "decision": decision, "gate": gate,
        "reason": reason, "kernel_version": proj.get("kernel_version"),
        "duration_ms": int((time.time() - t0) * 1000),
    })

    if decision == "deny" and mode == "enforce":
        _deny(reason)
    _allow()


if __name__ == "__main__":
    main()
