"""
pre_tool_use.py — the PreToolUse gate. The LLM may REQUEST a tool; this decides whether
it's allowed. [L1.0]

Decision precedence (first match wins) [codex#6, §2]:
  1. kill switch active            -> allow, silent, exit 0
  2. not an onboarded project      -> allow, silent, exit 0   (the 21 projects)
  3. mode == shadow                -> compute, LOG, allow, exit 0
  4. mode == enforce               -> compute; may DENY (fail-closed) with a reason

Any exception OUTSIDE an onboarded root -> allow, silent, exit 0 (fail open).
Output contract: allow = no stdout, exit 0. deny = the PreToolUse JSON, exit 0.
"""
import os
import sys
import json
import time

_VROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _VROOT)


def _allow():
    sys.exit(0)  # silence + exit 0 == proceed


def _deny(reason):
    out = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}
    sys.stdout.write(json.dumps(out) + "\n")  # newline + explicit flush so a deny is never
    sys.stdout.flush()                         # truncated/lost -> read as allow [A9]
    sys.exit(0)


def _hooklog(zaude_dir, payload):
    try:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        fd = os.open(os.path.join(zaude_dir, "hooklog.jsonl"),
                     os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)  # owner-only [A7]
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass  # observability must never break enforcement


def main():
    t0 = time.time()
    # --- read stdin (fail open on any problem) ---
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        _allow()

    try:
        from lib import paths, gates, trace, state as st
    except Exception:
        _allow()  # kernel import failure outside any project -> never block

    try:
        if paths.kill_switch_active():
            _allow()

        cwd = data.get("cwd") or os.getcwd()
        proj = paths.find_project(cwd)
        if proj is None:
            _allow()  # not onboarded -> the 21 projects are untouched
    except Exception:
        _allow()  # fail OPEN for anything we can't reason about outside a project

    # --- from here we ARE inside an onboarded project ---
    zaude_dir = proj["zaude_dir"]
    mode = proj["enforcement_mode"]
    tool = data.get("tool_name", "")
    tinput = data.get("tool_input", {}) or {}
    target = tinput.get("file_path") or tinput.get("notebook_path") or ""

    try:
        rows = trace.read_trace(zaude_dir)
        cur = st.project_state(rows)
        decision, reason, gate = gates.evaluate(cur, tool, target, zaude_dir)
    except (trace.TraceCorrupt, st.StateForged) as e:
        # Corrupt OR forged trace. In ENFORCE this fails CLOSED (a forged transition row
        # must NOT advance state — A1). In SHADOW we never block, only record. [D14]
        _hooklog(zaude_dir, {"ts": time.time(), "hook": "PreToolUse", "mode": mode,
                             "decision": "deny" if mode == "enforce" else "would-deny",
                             "reason": type(e).__name__,
                             "duration_ms": int((time.time() - t0) * 1000)})
        if mode == "enforce":
            _deny("Zaude trace is corrupt or forged (%s). Run `zaude repair` or recover "
                  "before editing. This is fail-closed by design." % e)
        _allow()
    except Exception:
        # an internal gate error inside a project: fail closed in enforce, allow in shadow.
        if mode == "enforce":
            _deny("Zaude gate error while evaluating this tool. Inspect .zaude or set "
                  "ZAUDE_DISABLE=1 to bypass.")
        _allow()

    _hooklog(zaude_dir, {
        "ts": time.time(), "hook": "PreToolUse", "cwd": cwd,
        "project_root": proj["root"], "mode": mode, "tool": tool, "target": target,
        "state": cur, "decision": decision, "gate": gate, "reason": reason,
        "kernel_version": proj.get("kernel_version"),
        "duration_ms": int((time.time() - t0) * 1000),
    })

    if decision == "deny" and mode == "enforce":
        _deny(reason)
    _allow()  # shadow mode, or an allow decision


if __name__ == "__main__":
    main()
