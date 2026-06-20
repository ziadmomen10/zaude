"""
user_prompt_submit.py (v0.2.0) — the always-on intent FRONT DOOR [Zaude 3, P0].

On every user prompt, map the natural-language request to the right Zaude command + safety mode
(auto/propose/confirm) via the deterministic router, and emit it as additionalContext so the
driver acts WITHOUT the operator typing a /command. ADVISORY ONLY: it SUGGESTS, never blocks a
prompt, never decides. Fail-open + kill-switch aware, exactly like the PreToolUse gate. If the
operator typed a /command, the front door stays silent — they drove. router.py called itself the
"C++ on C front door"; this hook is what finally puts it IN FRONT.
"""
import os
import sys
import json

_VROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _VROOT)


def _noop():
    sys.exit(0)


def _emit(text):
    try:
        out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                      "additionalContext": text}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    except Exception:
        pass
    sys.exit(0)


def main():
    # read payload (fail-open on anything)
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        _noop()

    try:
        prompt = (data.get("prompt") or "").strip()
    except Exception:
        _noop()
    if not prompt:
        _noop()

    # manual override: an explicit /command means the operator is driving — stay silent.
    if prompt.startswith("/"):
        _noop()

    try:
        from lib import paths, router
    except Exception:
        _noop()

    # kill switch — same absolute off-ramp as the gate
    try:
        if paths.kill_switch_active():
            _noop()
    except Exception:
        pass

    # best-effort current lifecycle state (lets the router gate lifecycle commands by precondition)
    current_state = None
    try:
        cwd = data.get("cwd") or os.getcwd()
        res = paths.resolve(cwd)
        if isinstance(res, dict) and res.get("status") == "onboarded":
            from lib import trace, state as st
            ctx = res["ctx"]
            rows = trace.read_trace(ctx["zaude_dir"], ctx["root"], verify=False)
            current_state = st.reduce(rows).get("current_state")
    except Exception:
        current_state = None

    # route (never raises by contract, but stay defensive)
    try:
        r = router.route(prompt, current_state)
    except Exception:
        _noop()

    cmd = r.get("command")
    mode = r.get("mode")
    if not cmd or mode == "ambiguous":
        _noop()  # unclear intent -> say nothing; the model proceeds normally

    conf = r.get("confidence", 0.0)
    blocked = r.get("blocked_by") or []
    alts = r.get("alternates") or []

    head = "[Zaude route] intent=/%s  mode=%s  confidence=%.2f" % (cmd, mode, conf)
    if alts:
        head += "  alts=" + ", ".join(
            "/%s:%.2f" % (a.get("command"), a.get("confidence", 0.0)) for a in alts[:2])

    if cmd == "build":
        guide = ("Run the /zbuild ENGINE (autonomous build loop: plan -> design -> implement -> "
                 "review panel -> verify, recorded in the signed trace, to tier-4). Full-auto: keep "
                 "going; HARD-STOP only on a destructive step, a CRITICAL/HIGH finding, or unclear scope.")
    elif mode == "auto":
        guide = "Safe/read-only — run `zaude %s` and report the result." % cmd
    elif mode == "confirm":
        guide = ("DESTRUCTIVE/irreversible — CONFIRM with the operator before running "
                 "`zaude %s`." % cmd)
    elif mode == "propose":
        guide = ("Full-auto: run `zaude %s` as part of the work and keep going; HARD-STOP only on "
                 "a destructive step, a CRITICAL/HIGH finding, or genuinely unclear scope." % cmd)
    else:
        _noop()

    if blocked:
        guide += "  (blocked_by: %s — resolve that first.)" % "; ".join(blocked)

    _emit(head + "\n" + guide +
          "\n(Routing is advisory — type the /command yourself to override.)")


if __name__ == "__main__":
    main()
