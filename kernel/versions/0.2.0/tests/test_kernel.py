"""
test_kernel.py (v0.2.0) — locks the hardened kernel's properties: tamper-evident trace,
validating reducer, the gate set (design/deploy/protect), waivers, fail-open, and the full
lifecycle integration. stdlib unittest. Run: python -m unittest discover -s tests
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
from lib import paths, trace, state as st, gates, keys as _keys  # noqa: E402

# repo root (in CI) or ~/.zaude (locally) — so generator/dist tests don't depend on a real ~/.zaude
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(VROOT)))
_POLICY = os.path.join(_REPO_ROOT, "policy", "policy.json")


def write_project(root, mode="enforce", marker=paths.ZAUDE_MARKER, schema=paths.SCHEMA_VERSION,
                  project_root=None):
    zd = os.path.join(root, ".zaude")
    os.makedirs(os.path.join(zd, "artifacts"), exist_ok=True)
    with open(os.path.join(zd, "project.json"), "w", encoding="utf-8") as f:
        json.dump({"zaude_marker": marker, "schema_version": schema,
                   "project_root": project_root if project_root is not None else paths._real(root),
                   "kernel_version": "0.2.0", "enforcement_mode": mode}, f)
    return zd


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="zaude test ")
        self.root = paths._real(self.tmp)
    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TraceTamperTests(TmpCase):
    def test_chain_roundtrip(self):
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "init"}, self.root)
        trace.append_row(zd, {"kind": "transition", "from": "Intake", "to": "Clarified"}, self.root)
        rows = trace.read_trace(zd, self.root, verify=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual(st.project_state(rows), "Clarified")

    def test_hand_appended_forgery_detected(self):
        # the v0.1.0 attack: append a fake transition row to fake progress
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "init"}, self.root)
        with open(os.path.join(zd, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","from":"Intake","to":"Approved"}\n')
        with self.assertRaises(trace.TraceForged):
            trace.read_trace(zd, self.root, verify=True)

    def test_content_tamper_breaks_mac(self):
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "init"}, self.root)
        trace.append_row(zd, {"kind": "transition", "from": "Intake", "to": "Clarified"}, self.root)
        p = os.path.join(zd, "trace.jsonl")
        lines = open(p, encoding="utf-8").read().splitlines()
        row = json.loads(lines[1]); row["to"] = "Released"        # tamper, keep old mac/seq/prev
        lines[1] = json.dumps(row, separators=(",", ":"))
        open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        with self.assertRaises(trace.TraceForged):
            trace.read_trace(zd, self.root, verify=True)

    def test_torn_tail_then_append(self):
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "init"}, self.root)
        with open(os.path.join(zd, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transitio')  # crash mid-write
        trace.append_row(zd, {"kind": "transition", "from": "Intake", "to": "Clarified"}, self.root)
        rows = trace.read_trace(zd, self.root, verify=True)  # must not raise
        self.assertEqual(st.project_state(rows), "Clarified")

    def test_missing_key_with_macs_fails_closed(self):
        # codex-CRIT: if the external key is gone but MACs exist, integrity is unverifiable
        zd = write_project(self.tmp)
        trace.append_row(zd, {"kind": "init"}, self.root)
        trace.append_row(zd, {"kind": "transition", "from": "Intake", "to": "Clarified"}, self.root)
        kp = _keys._key_path(self.root)
        if os.path.isfile(kp):
            os.remove(kp)
        with self.assertRaises(trace.TraceForged):
            trace.read_trace(zd, self.root, verify=True)

    def test_lock_ownership(self):
        zd = write_project(self.tmp)
        lp = trace.acquire_lock(zd)
        self.assertEqual(trace._lock_pid(lp), os.getpid())
        with open(lp, "w") as f:
            f.write("99999\n0\n")        # someone else owns it now
        trace.release_lock(lp)
        self.assertTrue(os.path.isfile(lp))   # not ours -> not removed
        os.remove(lp)


class ReducerTests(TmpCase):
    def test_legal_sequence_and_facts(self):
        rows = [
            {"kind": "transition", "from": "Intake", "to": "Clarified", "artifact": "requirements.json"},
            {"kind": "transition", "from": "Clarified", "to": "Prioritized", "artifact": "priority.json"},
            {"kind": "waiver", "gate": "design_before_impl"},
            {"kind": "release_token"},
        ]
        p = st.reduce(rows)
        self.assertEqual(p["current_state"], "Prioritized")
        self.assertIn("requirements.json", p["artifacts"])
        self.assertIn("design_before_impl", p["waived_gates"])
        self.assertTrue(p["release_token_active"])

    def test_illegal_transition_raises(self):
        with self.assertRaises(st.StateForged):
            st.reduce([{"kind": "transition", "from": "Intake", "to": "Released"}])

    def test_src_edit_allowed_only_from_approved(self):
        self.assertIn("Approved", st.SRC_EDIT_ALLOWED_FROM)
        self.assertNotIn("Designed", st.SRC_EDIT_ALLOWED_FROM)
        self.assertNotIn("Intake", st.SRC_EDIT_ALLOWED_FROM)

    def test_token_and_waiver_expiry(self):
        # codex-HIGH: expired grants must NOT remain active
        past = 1000.0
        rows = [{"kind": "release_token", "expires_at": past},
                {"kind": "waiver", "gate": "design_before_impl", "expires_at": past}]
        expired = st.reduce(rows, now=past + 10)
        self.assertFalse(expired["release_token_active"])
        self.assertNotIn("design_before_impl", expired["waived_gates"])
        live = st.reduce(rows, now=past - 10)
        self.assertTrue(live["release_token_active"])
        self.assertIn("design_before_impl", live["waived_gates"])


class GateTests(TmpCase):
    def _ev(self, current, tool, tinput, waived=None, token=False, risk=None):
        proj = st.Projection(current_state=current, waived_gates=set(waived or []),
                             release_token_active=token, risk_tier=risk)
        return gates.evaluate(proj, tool, tinput, os.path.join(self.tmp, ".zaude"))

    def test_design_gate_light_by_default(self):
        # LOW/unclassified work codes freely (Deen: don't over-gate)
        self.assertEqual(self._ev("Intake", "Edit", {"file_path": "src/a.ts"})[0], "allow")
        self.assertEqual(self._ev("Intake", "Edit", {"file_path": "src/a.ts"}, risk="T1")[0], "allow")
        self.assertEqual(self._ev("Intake", "MultiEdit", {"file_path": "src/a.ts"}, risk="T2")[0], "allow")
        # HIGH-risk (T3/T4) work IS gated until Approved
        d, _, g = self._ev("Intake", "Edit", {"file_path": "src/a.ts"}, risk="T4")
        self.assertEqual((d, g), ("deny", "design_before_impl"))
        self.assertEqual(self._ev("Approved", "Edit", {"file_path": "src/a.ts"}, risk="T4")[0], "allow")

    def test_protect_zaude_not_waivable(self):
        zd = os.path.join(self.tmp, ".zaude")
        d, _, g = self._ev("Approved", "Write", {"file_path": os.path.join(zd, "trace.jsonl")})
        self.assertEqual(d, "deny"); self.assertEqual(g, "protect_zaude")
        # even waiving it does NOT unlock (not waivable)
        d, _, _ = self._ev("Approved", "Write", {"file_path": os.path.join(zd, "trace.jsonl")},
                           waived=["protect_zaude"])
        self.assertEqual(d, "deny")

    def test_deploy_gate(self):
        d, _, g = self._ev("Approved", "Bash", {"command": "bash deploy.sh"})
        self.assertEqual(d, "deny"); self.assertEqual(g, "deploy_needs_release_token")
        d, _, _ = self._ev("Released", "Bash", {"command": "bash deploy.sh"}, token=True)
        self.assertEqual(d, "allow")
        d, _, _ = self._ev("Approved", "Bash", {"command": "ls -la"})  # not a deploy cmd
        self.assertEqual(d, "allow")

    def test_waiver_downgrades_design_gate(self):
        # the gate only fires for high-risk; a waiver then downgrades it
        d, _, _ = self._ev("Intake", "Edit", {"file_path": "src/a.ts"},
                           waived=["design_before_impl"], risk="T4")
        self.assertEqual(d, "allow-waived")

    def test_windows_filename_tricks(self):
        self.assertTrue(gates.is_source("src/app.ts."))
        self.assertTrue(gates.is_source("src/app.ts "))
        self.assertTrue(gates.is_source("src/app.ts:stream"))

    def test_waiver_name_hyphen_normalized(self):
        # codex-MED: the friendly hyphenated waiver name must match the underscore gate id
        d, _, _ = self._ev("Intake", "Edit", {"file_path": "src/a.ts"},
                           waived=["design-before-impl"], risk="T4")
        self.assertEqual(d, "allow-waived")


class FailOpenTests(TmpCase):
    def test_non_onboarded(self):
        self.assertIsNone(paths.find_project(self.tmp))
    def test_nested_independent_project(self):
        write_project(self.tmp)
        child = os.path.join(self.tmp, "node_thing")
        os.makedirs(os.path.join(child, "src"))
        open(os.path.join(child, "package.json"), "w").write("{}")
        self.assertIsNone(paths.find_project(os.path.join(child, "src")))


class SelfHostingTests(TmpCase):
    """Zaude must let you use Zaude to develop Zaude (enhance it, build vNext). Source — INCLUDING
    Zaude's own kernel source — is normal lifecycle-gated source, never the never-waivable
    protected class. The only never-waivable protection is the active project's own `.zaude/`
    STATE dir. So you can always evolve the framework; you're never trapped."""

    def _ev(self, current, tool, tinput, waived=None, risk=None):
        proj = st.Projection(current_state=current, waived_gates=set(waived or []),
                             release_token_active=False, risk_tier=risk)
        return gates.evaluate(proj, tool, tinput, os.path.join(self.tmp, ".zaude"))

    def test_kernel_source_editable_after_approve(self):
        d, _, _ = self._ev("Approved", "Edit", {"file_path": os.path.join(self.tmp, "lib", "trace.py")})
        self.assertEqual(d, "allow")

    def test_kernel_source_flows_by_default(self):
        # editing Zaude's own source is light-by-default like any source
        self.assertEqual(self._ev("Intake", "Edit", {"file_path": os.path.join(self.tmp, "lib", "trace.py")})[0], "allow")

    def test_kernel_source_is_waivable_not_hard_blocked(self):
        # even when classified HIGH-risk, it's the WAIVABLE design gate, not protect_zaude
        p = os.path.join(self.tmp, "lib", "trace.py")
        d, _, g = self._ev("Intake", "Edit", {"file_path": p}, risk="T4")
        self.assertEqual((d, g), ("deny", "design_before_impl"))
        d2, _, _ = self._ev("Intake", "Edit", {"file_path": p}, waived=["design_before_impl"], risk="T4")
        self.assertEqual(d2, "allow-waived")   # a logged waiver frees framework development

    def test_only_state_dir_is_never_waivable(self):
        zd = os.path.join(self.tmp, ".zaude")
        d, _, g = self._ev("Approved", "Write", {"file_path": os.path.join(zd, "trace.jsonl")})
        self.assertEqual((d, g), ("deny", "protect_zaude"))               # state is sacred
        d2, _, _ = self._ev("Approved", "Write", {"file_path": os.path.join(self.tmp, "lib", "gates.py")})
        self.assertEqual(d2, "allow")                                     # but source never is

    def test_shadow_mode_never_blocks_self_dev(self):
        # the recommended self-dev mode: full audit trail, nothing blocked
        zd = write_project(self.tmp, "shadow")
        p = subprocess.run([sys.executable, os.path.join(VROOT, "zhook.py"), "pre_tool_use"],
                           input=json.dumps({"cwd": self.tmp, "tool_name": "Edit",
                                             "tool_input": {"file_path": os.path.join(self.tmp, "lib", "trace.py")}}).encode(),
                           stdout=subprocess.PIPE)
        self.assertEqual(p.stdout.decode().strip(), "")   # shadow: allowed even at Intake


class GeneratorTests(TmpCase):
    def test_generate_produces_commands_agents_hook(self):
        from lib import generator
        out = os.path.join(self.tmp, "gen")
        r = generator.generate(out_dir=out, policy_path=_POLICY)
        self.assertGreaterEqual(r["commands"], 20)
        self.assertGreaterEqual(r["agents"], 2)
        self.assertTrue(os.path.isfile(os.path.join(out, "commands", "ship.md")))
        self.assertTrue(os.path.isfile(os.path.join(out, "agents", "evidence-verifier.md")))
        hb = json.load(open(os.path.join(out, "hook-block.json")))
        self.assertIn("Edit", hb["matcher"])
        self.assertIn("zhook.py", hb["hooks"][0]["command"])
        man = json.load(open(os.path.join(out, "manifest.json")))
        self.assertEqual(man["policy_sha"], r["policy_sha"])

    def test_generate_idempotent(self):
        from lib import generator
        out = os.path.join(self.tmp, "gen")
        generator.generate(out_dir=out, policy_path=_POLICY)
        a = open(os.path.join(out, "commands", "ship.md"), encoding="utf-8").read()
        generator.generate(out_dir=out, policy_path=_POLICY)
        b = open(os.path.join(out, "commands", "ship.md"), encoding="utf-8").read()
        self.assertEqual(a, b)

    def test_no_secret_in_generated(self):
        import glob
        from lib import generator
        out = os.path.join(self.tmp, "gen")
        generator.generate(out_dir=out, policy_path=_POLICY)
        for f in glob.glob(os.path.join(out, "**", "*"), recursive=True):
            if os.path.isfile(f):
                self.assertNotIn("ghp_", open(f, encoding="utf-8").read())


class DistTests(TmpCase):
    def setUp(self):
        super().setUp()
        from lib import dist
        self._oz = dist.ZROOT
        dist.ZROOT = _REPO_ROOT   # package from the repo (CI) / ~/.zaude (local), not a fixed path

    def tearDown(self):
        from lib import dist
        dist.ZROOT = self._oz
        super().tearDown()

    def test_package_excludes_secrets_includes_scripts(self):
        import glob
        from lib import dist
        out = os.path.join(self.tmp, "d")
        dist.package(out)
        self.assertTrue(os.path.isfile(os.path.join(out, "install.sh")))
        self.assertTrue(os.path.isfile(os.path.join(out, "install.ps1")))
        self.assertTrue(os.path.isdir(os.path.join(out, "kernel")))
        self.assertFalse(os.path.isdir(os.path.join(out, "secrets")))
        from lib.dist import _TOKEN_RE
        for f in glob.glob(os.path.join(out, "**", "*"), recursive=True):
            if os.path.isfile(f):  # no REAL token (20+ chars) — short test fakes are fine
                self.assertIsNone(_TOKEN_RE.search(open(f, encoding="utf-8", errors="ignore").read()), f)

    def test_package_refuses_inside_zaude(self):
        from lib import dist
        with self.assertRaises(ValueError):
            dist.package(os.path.join(dist.ZROOT, "x"))


class SecretSafetyTests(TmpCase):
    """The GitHub PAT must come only from a real file under ~/.zaude/secrets — never a symlink
    (which could point into a pushed repo) or a file elsewhere. [codex]"""
    def test_secret_path_hardening(self):
        from lib import pm_github
        sd = os.path.join(self.tmp, "secrets"); os.makedirs(sd)
        good = os.path.join(sd, "github-pat")
        with open(good, "w") as f:
            f.write("ghp_faketoken")
        o_dir, o_sec = pm_github._SECRET_DIR, pm_github._SECRET
        try:
            pm_github._SECRET_DIR, pm_github._SECRET = sd, good
            self.assertTrue(pm_github.have_token())            # real file under the dir: ok
            outside = os.path.join(self.tmp, "github-pat")
            with open(outside, "w") as f:
                f.write("ghp_faketoken")
            pm_github._SECRET = outside
            self.assertFalse(pm_github.have_token())           # outside the secrets dir: refused
            link = os.path.join(sd, "link-pat")
            try:
                os.symlink(good, link)
                pm_github._SECRET = link
                self.assertFalse(pm_github.have_token())       # symlink: refused
            except (OSError, NotImplementedError, AttributeError):
                pass  # symlink may require privilege on Windows
        finally:
            pm_github._SECRET_DIR, pm_github._SECRET = o_dir, o_sec


class HookAndIntegrationTests(TmpCase):
    def _hook(self, payload, disabled=False):
        env = dict(os.environ)
        env.pop("ZAUDE_DISABLE", None)
        if disabled:
            env["ZAUDE_DISABLE"] = "1"
        p = subprocess.run([sys.executable, os.path.join(VROOT, "zhook.py"), "pre_tool_use"],
                           input=json.dumps(payload).encode(), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=env)
        return p.returncode, p.stdout.decode().strip()

    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"),
                               "--path", self.tmp] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_non_onboarded_silent_allow(self):
        rc, out = self._hook({"cwd": self.tmp, "tool_name": "Edit",
                              "tool_input": {"file_path": "x.ts"}})
        self.assertEqual((rc, out), (0, ""))

    def test_forged_append_denied_in_enforce(self):
        write_project(self.tmp, "enforce")
        trace.append_row(os.path.join(self.tmp, ".zaude"), {"kind": "init"}, self.root)
        with open(os.path.join(self.tmp, ".zaude", "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","from":"Intake","to":"Approved"}\n')
        rc, out = self._hook({"cwd": self.tmp, "tool_name": "Edit",
                              "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_low_risk_code_flows_immediately(self):
        # LIGHT by default: unclassified/low-risk source edits flow at Intake (no nag)
        self._cli("init", "--text", "x", "--mode", "enforce")
        edit = {"cwd": self.tmp, "tool_name": "Edit",
                "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}}
        self.assertEqual(self._hook(edit)[1], "")

    def test_high_risk_blocks_code_until_approved(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        for cmd in (["clarify", "--acceptance", "x"], ["prioritize", "--decision", "n"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T4"]):
            self._cli(*cmd)
        edit = {"cwd": self.tmp, "tool_name": "Edit",
                "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}}
        self.assertEqual(json.loads(self._hook(edit)[1])["hookSpecificOutput"]["permissionDecision"], "deny")
        self._cli("approve", "--by", "op")
        self.assertEqual(self._hook(edit)[1], "")

    def test_deploy_gate_independent_of_risk(self):
        deploy = {"cwd": self.tmp, "tool_name": "Bash", "tool_input": {"command": "bash deploy.sh"}}
        self.assertEqual(self._cli("init", "--text", "x", "--mode", "enforce").returncode, 0)
        self.assertEqual(json.loads(self._hook(deploy)[1])["hookSpecificOutput"]["permissionDecision"], "deny")
        for cmd in (["clarify", "--acceptance", "x"], ["prioritize", "--decision", "n"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T1"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "pytest", "--exit", "0"], ["review", "--unresolved", "0"],
                    ["verify"], ["shippable"], ["ship", "--deploy-id", "d1"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)
        self.assertEqual(self._hook(deploy)[1], "")  # token active -> deploy allowed


class FastLaneTests(TmpCase):
    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_fast_reaches_approved_in_one_command(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertEqual(self._cli("fast", "--note", "tiny fix", "--tier", "T1").returncode, 0)
        proj = json.loads(self._cli("status").stdout)
        self.assertEqual(proj["current_state"], "Approved")
        self.assertEqual(proj["risk_tier"], "T1")

    def test_fast_refuses_high_risk(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertEqual(self._cli("fast", "--note", "risky", "--tier", "T4").returncode, 3)

    def test_fast_ship_keeps_the_evidence_gate(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._cli("fast", "--note", "tiny", "--tier", "T1")
        self.assertEqual(self._cli("fast-ship", "--tested-exit", "1").returncode, 3)   # broken -> refused
        self.assertEqual(self._cli("fast-ship", "--tested-exit", "0").returncode, 0)   # green -> ships
        proj = json.loads(self._cli("status").stdout)
        self.assertEqual(proj["current_state"], "Released")
        self.assertTrue(proj["release_token_active"])

    def test_ship_refuses_with_unresolved_findings(self):
        self.assertEqual(self._cli("init", "--text", "x", "--mode", "enforce").returncode, 0)
        for cmd in (["clarify", "--acceptance", "x"], ["prioritize", "--decision", "n"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T1"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "t", "--exit", "0"], ["review", "--unresolved", "2"],
                    ["verify"], ["shippable"]):
            self._cli(*cmd)
        # ship must refuse: 2 unresolved CRITICAL/HIGH in the review ledger
        self.assertEqual(self._cli("ship").returncode, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
