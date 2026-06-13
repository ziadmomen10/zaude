"""
test_kernel.py — locks the kernel's safety properties. stdlib unittest only.
Run: python -m unittest discover -s tests   (from the version root)
"""
import os
import sys
import json
import time
import shutil
import tempfile
import subprocess
import unittest

VROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, VROOT)
from lib import paths, trace, state as st, gates  # noqa: E402


def write_project(root, mode="enforce", marker=paths.ZAUDE_MARKER,
                  schema=paths.SCHEMA_VERSION, project_root=None):
    zd = os.path.join(root, ".zaude")
    os.makedirs(os.path.join(zd, "artifacts"), exist_ok=True)
    obj = {"zaude_marker": marker, "schema_version": schema,
           "project_root": project_root if project_root is not None else paths._real(root),
           "kernel_version": "0.1.0", "enforcement_mode": mode}
    with open(os.path.join(zd, "project.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return zd


class TmpCase(unittest.TestCase):
    def setUp(self):
        # include a space to exercise codex-SF10
        self.tmp = tempfile.mkdtemp(prefix="zaude test ")
    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TraceTests(TmpCase):
    def test_append_replay_roundtrip(self):
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "init"})
        trace.append_row(zd, {"kind": "transition", "from": "Intake", "to": "Clarified"})
        rows = trace.read_trace(zd)
        self.assertEqual(len(rows), 2)
        self.assertEqual(st.project_state(rows), "Clarified")

    def test_corrupt_last_line_quarantined(self):
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "transition", "from": "Intake", "to": "Clarified"})
        with open(os.path.join(zd, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","to":"Desig')  # partial write, no newline
        rows = trace.read_trace(zd)  # must NOT raise
        self.assertEqual(st.project_state(rows), "Clarified")

    def test_corrupt_interior_line_raises(self):
        zd = write_project(self.tmp)
        p = os.path.join(zd, "trace.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write("NOT JSON\n")
            f.write(json.dumps({"kind": "init"}) + "\n")
        with self.assertRaises(trace.TraceCorrupt):
            trace.read_trace(zd)

    def test_torn_tail_then_append_does_not_brick(self):
        # T2 (codex-C1 / cr-C1): a torn partial write + a later append must NOT fuse into an
        # interior-corrupt line. The heal truncates the never-committed partial.
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "init"})
        with open(os.path.join(zd, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","from":"Intake","to":"Clari')  # crash mid-write
        trace.append_row(zd, {"kind": "transition", "from": "Intake", "to": "Clarified"})
        rows = trace.read_trace(zd)  # must NOT raise
        self.assertEqual(st.project_state(rows), "Clarified")
        # the partial was dropped, exactly one transition survived
        self.assertEqual(sum(1 for r in rows if r.get("kind") == "transition"), 1)

    def test_atomic_write_and_lock_stale_recovery(self):
        zd = write_project(self.tmp)
        trace.write_json_atomic(os.path.join(zd, "state.json"), {"a": 1})
        self.assertEqual(trace.read_state(zd), {"a": 1})
        lp = trace.acquire_lock(zd)
        trace.release_lock(lp)
        # forge a stale lock, prove recovery
        with open(os.path.join(zd, ".lock"), "w") as f:
            f.write("99999\n0\n")
        old = time.time() - 120
        os.utime(os.path.join(zd, ".lock"), (old, old))
        lp2 = trace.acquire_lock(zd, stale_after=30.0)  # should reclaim
        self.assertTrue(os.path.isfile(lp2))
        self.assertEqual(trace._lock_pid(lp2), os.getpid())  # we now own it
        # a foreign-owned lock is NOT removed by our release (A5)
        with open(lp2, "w") as f:
            f.write("99999\n0\n")
        trace.release_lock(lp2)
        self.assertTrue(os.path.isfile(lp2))  # not ours -> left intact
        os.remove(lp2)


class GateTests(TmpCase):
    def test_design_gate_truth_table(self):
        # source edit blocked before Designed
        d, _ = gates.design_before_impl("Intake", "Edit", "src/app.ts", None)
        self.assertEqual(d, "deny")
        d, _ = gates.design_before_impl("Clarified", "Write", "x/y.py", None)
        self.assertEqual(d, "deny")
        d, _ = gates.design_before_impl("Intake", "MultiEdit", "src/app.ts", None)  # A4
        self.assertEqual(d, "deny")
        # allowed at/after Designed
        d, _ = gates.design_before_impl("Designed", "Edit", "src/app.ts", None)
        self.assertEqual(d, "allow")
        # non-source always allowed
        d, _ = gates.design_before_impl("Intake", "Edit", "README.md", None)
        self.assertEqual(d, "allow")
        # non-mutating tools ignored
        d, _ = gates.design_before_impl("Intake", "Read", "src/app.ts", None)
        self.assertEqual(d, "allow")

    def test_mixed_separators_and_case(self):
        self.assertTrue(gates.is_source("SRC\\App.TS"))   # windows sep + upper
        self.assertTrue(gates.is_source("a/b/c.PY"))
        self.assertFalse(gates.is_source("a/b/notes.txt"))

    def test_windows_filename_tricks(self):
        # A4: trailing dot/space and ADS must NOT dodge the source gate
        self.assertTrue(gates.is_source("src/app.ts."))      # trailing dot -> Win opens app.ts
        self.assertTrue(gates.is_source("src/app.ts "))      # trailing space
        self.assertTrue(gates.is_source("src/app.ts:stream"))  # NTFS alternate data stream

    def test_protect_zaude_gate(self):
        # A1: a mutating tool may never write under .zaude/ (would forge state)
        zd = write_project(self.tmp, mode="enforce")
        d, reason = gates.protect_zaude("Designed", "Write",
                                        os.path.join(zd, "trace.jsonl"), zd)
        self.assertEqual(d, "deny")
        # a normal source file elsewhere is not protected by THIS gate
        d, _ = gates.protect_zaude("Designed", "Write", os.path.join(self.tmp, "src", "a.ts"), zd)
        self.assertEqual(d, "allow")


class FindProjectTests(TmpCase):
    def test_valid_onboarded(self):
        write_project(self.tmp, mode="shadow")
        proj = paths.find_project(self.tmp)
        self.assertIsNotNone(proj)
        self.assertEqual(proj["enforcement_mode"], "shadow")
        self.assertEqual(proj["root"], paths._real(self.tmp))

    def test_resolves_from_child_dir(self):
        write_project(self.tmp)
        child = os.path.join(self.tmp, "packages", "x", "src")
        os.makedirs(child)
        self.assertIsNotNone(paths.find_project(child))

    def test_missing_marker_fails_open(self):
        write_project(self.tmp, marker="not-zaude")
        self.assertIsNone(paths.find_project(self.tmp))

    def test_schema_mismatch_fails_open(self):
        write_project(self.tmp, schema=999)
        self.assertIsNone(paths.find_project(self.tmp))

    def test_parent_owned_root_mismatch_fails_open(self):
        # project.json claims a DIFFERENT root than where it lives -> must fail open
        write_project(self.tmp, project_root=os.path.join(self.tmp, "elsewhere"))
        self.assertIsNone(paths.find_project(self.tmp))

    def test_garbled_json_fails_open(self):
        zd = os.path.join(self.tmp, ".zaude")
        os.makedirs(zd)
        with open(os.path.join(zd, "project.json"), "w") as f:
            f.write("{ this is not json")
        self.assertIsNone(paths.find_project(self.tmp))

    def test_no_zaude_fails_open(self):
        self.assertIsNone(paths.find_project(self.tmp))

    def test_git_boundary_stops_walk(self):
        # a child repo with .git but no .zaude must NOT bind to a parent's .zaude
        write_project(self.tmp)  # parent onboarded
        child_repo = os.path.join(self.tmp, "vendored")
        os.makedirs(os.path.join(child_repo, ".git"))
        sub = os.path.join(child_repo, "src")
        os.makedirs(sub)
        self.assertIsNone(paths.find_project(sub))

    def test_git_FILE_boundary_stops_walk(self):
        # T3 / A2 / cr-M1: worktrees & submodules use a .git FILE, not a dir
        write_project(self.tmp)
        child = os.path.join(self.tmp, "wt")
        os.makedirs(os.path.join(child, "src"))
        with open(os.path.join(child, ".git"), "w") as f:
            f.write("gitdir: /somewhere/.git/worktrees/wt\n")
        self.assertIsNone(paths.find_project(os.path.join(child, "src")))

    def test_nested_independent_project_boundary(self):
        # T3 / A2 / sec-C1: a non-git nested project (package.json) under an onboarded parent
        # must NOT inherit the parent's enforcement.
        write_project(self.tmp)
        child = os.path.join(self.tmp, "node_thing")
        os.makedirs(os.path.join(child, "src"))
        with open(os.path.join(child, "package.json"), "w") as f:
            f.write("{}")
        self.assertIsNone(paths.find_project(os.path.join(child, "src")))

    def test_kill_switch_env(self):
        os.environ["ZAUDE_DISABLE"] = "1"
        try:
            self.assertTrue(paths.kill_switch_active())
        finally:
            del os.environ["ZAUDE_DISABLE"]
        self.assertFalse(paths.kill_switch_active())


class HookContractTests(TmpCase):
    """Invoke the real hook via the launcher with a crafted stdin payload and assert the
    Claude Code output contract. [codex#5]"""
    def _run_hook(self, payload):
        zhook = os.path.join(VROOT, "zhook.py")
        p = subprocess.run([sys.executable, zhook, "pre_tool_use"],
                           input=json.dumps(payload).encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_non_onboarded_is_silent_allow(self):
        rc, out, err = self._run_hook({"cwd": self.tmp, "tool_name": "Edit",
                                       "tool_input": {"file_path": "x.ts"}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")  # EXACTLY nothing

    def test_enforce_denies_source_before_design(self):
        write_project(self.tmp, mode="enforce")
        rc, out, err = self._run_hook({"cwd": self.tmp, "tool_name": "Edit",
                                       "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}})
        self.assertEqual(rc, 0)
        obj = json.loads(out)
        self.assertEqual(obj["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_shadow_logs_but_allows(self):
        zd = write_project(self.tmp, mode="shadow")
        rc, out, err = self._run_hook({"cwd": self.tmp, "tool_name": "Edit",
                                       "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")  # shadow never blocks
        with open(os.path.join(zd, "hooklog.jsonl")) as f:
            log = [json.loads(l) for l in f if l.strip()]
        self.assertTrue(any(r["decision"] == "deny" and r["mode"] == "shadow" for r in log))

    def test_kill_switch_silences_enforce(self):
        write_project(self.tmp, mode="enforce")
        os.environ["ZAUDE_DISABLE"] = "1"
        try:
            rc, out, err = self._run_hook({"cwd": self.tmp, "tool_name": "Edit",
                                           "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}})
        finally:
            del os.environ["ZAUDE_DISABLE"]
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")  # disabled -> allow

    def test_garbage_stdin_fails_open(self):
        zhook = os.path.join(VROOT, "zhook.py")
        p = subprocess.run([sys.executable, zhook, "pre_tool_use"],
                           input=b"not json at all",
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.decode(), "")

    def test_forged_transition_row_is_denied(self):
        # T1 (sec-H2 / codex-CRIT): appending a fake `to:Designed` row must NOT unlock edits;
        # validating replay raises StateForged -> the hook fails closed in enforce mode.
        zd = write_project(self.tmp, mode="enforce")
        trace.append_row(zd, {"kind": "transition", "to": "Designed"})  # forged: no legal `from`
        rc, out, err = self._run_hook({"cwd": self.tmp, "tool_name": "Edit",
                                       "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}})
        self.assertEqual(rc, 0)
        obj = json.loads(out)
        self.assertEqual(obj["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("forged", obj["hookSpecificOutput"]["permissionDecisionReason"].lower())

    def test_zaude_dir_write_is_denied(self):
        # T4 (A1): a mutating tool may never write the trace itself, even at Designed.
        zd = write_project(self.tmp, mode="enforce")
        rc, out, err = self._run_hook({"cwd": self.tmp, "tool_name": "Write",
                                       "tool_input": {"file_path": os.path.join(zd, "trace.jsonl")}})
        obj = json.loads(out)
        self.assertEqual(obj["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_cli_and_hook_end_to_end(self):
        # T5: run the real CLI to advance state and prove the hook flips deny->allow.
        def cli(*a):
            return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"),
                                   "--path", self.tmp] + list(a),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        src = os.path.join(self.tmp, "src", "a.ts")
        payload = {"cwd": self.tmp, "tool_name": "Edit", "tool_input": {"file_path": src}}

        self.assertEqual(cli("init", "--text", "add export", "--mode", "enforce").returncode, 0)
        # before design -> deny
        _, out, _ = self._run_hook(payload)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(cli("clarify", "--acceptance", "valid csv").returncode, 0)
        self.assertEqual(cli("design", "--approach", "stream rows", "--decision", "D1").returncode, 0)
        # after design -> allow (empty output)
        _, out2, _ = self._run_hook(payload)
        self.assertEqual(out2, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
