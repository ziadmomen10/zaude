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
    out = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
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


def main():
    t0 = time.time()
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        _allow()

    try:
        from lib import paths, gates, trace, state as st
    except Exception:
        _allow()

    try:
        if paths.kill_switch_active():
            _allow()
        cwd = data.get("cwd") or os.getcwd()
        proj = paths.find_project(cwd)
        if proj is None:
            _allow()
    except Exception:
        _allow()

    zaude_dir = proj["zaude_dir"]
    root = proj["root"]
    mode = proj["enforcement_mode"]
    tool = data.get("tool_name", "")
    tinput = data.get("tool_input", {}) or {}
    if not isinstance(tinput, dict):
        tinput = {}
    target = tinput.get("file_path") or tinput.get("notebook_path") or ""

    try:
        rows = trace.read_trace(zaude_dir, root, verify=True)
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
