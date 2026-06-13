"""
cli.py — the deterministic worker behind the slash commands. Slash commands COMMIT
transitions; the LLM only invokes them. [R1]

  zaude init   --text "<request>"            -> .zaude/, request.json, state=Intake
  zaude clarify --acceptance "<criteria>"    -> requirements.json, Intake->Clarified
  zaude design --approach "<a>" --decision "<id>" -> design.json, Clarified->Designed
  zaude implement                            -> Designed->Implemented
  zaude status                               -> resume projection (rebuilt from trace)
  zaude repair                               -> rebuild state.json from trace
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import paths, trace, state as st  # noqa: E402


def _kernel_version():
    try:
        with open(os.path.join(os.path.expanduser("~"), ".zaude", "kernel", "CURRENT"),
                  "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.1.0"


def _zaude_dir(root):
    return os.path.join(root, ".zaude")


def _project_kernel_version(zaude_dir):
    """The kernel_version that GOVERNS this project (its stamp), not the global CURRENT. [A8]"""
    try:
        with open(os.path.join(zaude_dir, "project.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("kernel_version")
    except Exception:
        return None


def _projection(zaude_dir):
    """A PURE projection of the trace (no wall-clock, no global state) so it can be
    checksum-compared for staleness. [A8, arch-L4]"""
    rows = trace.read_trace(zaude_dir)
    cur = st.project_state(rows)
    last = None
    for r in rows:
        if r.get("kind") == "transition":
            last = r
    return {
        "current_state": cur,
        "allowed_next_states": st.next_states(cur),
        "kernel_version": _project_kernel_version(zaude_dir),
        "last_transition": last,
    }


def _refresh_state(zaude_dir):
    trace.write_state(zaude_dir, _projection(zaude_dir))


def _commit(zaude_dir, frm, to, command, artifact_name=None, artifact_obj=None):
    lp = trace.acquire_lock(zaude_dir)
    committed = False
    try:
        rows = trace.read_trace(zaude_dir)
        cur = st.project_state(rows)
        if cur != frm:
            sys.stderr.write("refused: %s requires state=%s but state=%s\n" % (command, frm, cur))
            return 3
        if not st.can_transition(frm, to):
            sys.stderr.write("refused: illegal transition %s -> %s\n" % (frm, to))
            return 3
        # Artifact is written (atomically) BEFORE the transition row that references it, so a
        # crash leaves at most an inert orphan and state stays BACK (fail-safe toward blocked).
        # Content-addressing is the Phase-2 hardening (B7).
        if artifact_name is not None:
            apath = os.path.join(zaude_dir, "artifacts", artifact_name)
            trace.write_json_atomic(apath, artifact_obj)
        trace.append_row(zaude_dir, {
            "kind": "transition", "from": frm, "to": to,
            "command": command, "artifact": artifact_name,
        })
        committed = True
        # Refresh the disposable projection while still holding the lock. A projection
        # failure must NOT present as a commit failure — the trace already won. [codex-H1]
        try:
            _refresh_state(zaude_dir)
        except Exception as e:
            sys.stderr.write("note: transition committed; projection refresh failed (%s); "
                             "`zaude repair` will rebuild it.\n" % e)
    finally:
        trace.release_lock(lp)
    if committed:
        print("OK: %s  %s -> %s" % (command, frm, to))
        return 0
    return 1


# ---------------------------------------------------------------- commands
def cmd_init(args):
    root = paths._real(args.path or os.getcwd())
    zd = _zaude_dir(root)
    # Refuse to clobber an already-onboarded project (would overwrite project.json/request
    # and desync them from the existing trace). [A10, cr-M4]
    if not getattr(args, "force", False) and paths.find_project(root) is not None:
        sys.stderr.write("refused: %s is already an onboarded Zaude project. Use --force to "
                         "re-init (this rewrites project.json/request.json).\n" % root)
        return 3
    os.makedirs(os.path.join(zd, "artifacts"), exist_ok=True)
    project = {
        "zaude_marker": paths.ZAUDE_MARKER,
        "schema_version": paths.SCHEMA_VERSION,
        "project_root": root,
        "kernel_version": _kernel_version(),
        "enforcement_mode": args.mode,
    }
    trace.write_json_atomic(os.path.join(zd, "project.json"), project)
    # request.json (the Intake artifact)
    trace.write_json_atomic(os.path.join(zd, "artifacts", "request.json"),
                            {"id": "REQ-INTAKE", "text": args.text, "source": "operator"})
    # seed trace if empty
    if not trace.read_trace(zd):
        trace.append_row(zd, {"kind": "init", "root": root, "mode": args.mode})
    _refresh_state(zd)
    print("initialized %s (mode=%s)" % (zd, args.mode))
    return 0


def _resolve(args):
    proj = paths.find_project(args.path or os.getcwd())
    if proj is None:
        sys.stderr.write("not an onboarded Zaude project (no valid .zaude/project.json)\n")
        sys.exit(4)
    return proj["zaude_dir"]


def cmd_clarify(args):
    zd = _resolve(args)
    req = {}
    try:
        with open(os.path.join(zd, "artifacts", "request.json"), "r", encoding="utf-8") as f:
            req = json.load(f)
    except Exception:
        pass
    obj = [{"req_id": "REQ-1", "statement": req.get("text", ""), "acceptance": args.acceptance}]
    return _commit(zd, "Intake", "Clarified", "/clarify", "requirements.json", obj)


def cmd_design(args):
    zd = _resolve(args)
    obj = {"approach": args.approach, "alternatives": [],
           "decision_id": args.decision, "risks": []}
    return _commit(zd, "Clarified", "Designed", "/design", "design.json", obj)


def cmd_implement(args):
    zd = _resolve(args)
    return _commit(zd, "Designed", "Implemented", "/implement", None, None)


def cmd_status(args):
    zd = _resolve(args)
    print(json.dumps(_projection(zd), indent=2))
    return 0


def cmd_repair(args):
    zd = _resolve(args)
    try:
        rows = trace.read_trace(zd)        # raises TraceCorrupt on interior corruption
        cur = st.project_state(rows)       # raises StateForged on an illegal transition row
    except trace.TraceCorrupt as e:
        sys.stderr.write("HALT: %s — append-only trace is corrupt; manual recovery required "
                         "(Phase-2: `repair --force-truncate-at`).\n" % e)
        return 5
    except st.StateForged as e:
        sys.stderr.write("HALT: %s — the trace contains a forged/illegal transition; manual "
                         "review required (the projection cannot be trusted).\n" % e)
        return 5
    _refresh_state(zd)
    print("repaired: state.json rebuilt from %d trace rows -> %s" % (len(rows), cur))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="zaude")
    p.add_argument("--path", default=None, help="project dir (default: cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init"); sp.add_argument("--text", required=True)
    sp.add_argument("--mode", choices=("shadow", "enforce"), default="enforce")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("clarify"); sp.add_argument("--acceptance", required=True)
    sp.set_defaults(fn=cmd_clarify)

    sp = sub.add_parser("design"); sp.add_argument("--approach", required=True)
    sp.add_argument("--decision", required=True); sp.set_defaults(fn=cmd_design)

    sp = sub.add_parser("implement"); sp.set_defaults(fn=cmd_implement)
    sp = sub.add_parser("status"); sp.set_defaults(fn=cmd_status)
    sp = sub.add_parser("repair"); sp.set_defaults(fn=cmd_repair)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
