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
from lib import paths, trace, state as st, gates, keys as _keys, vault  # noqa: E402

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


class FailClosedMarkerTests(TmpCase):
    """A PRESENT-but-corrupt .zaude/project.json must fail CLOSED in the hook (codex fail-open #1):
    silently losing enforcement because one file got garbled is the gap this closes. Parseable
    markers (clone with a foreign root, other tools, schema drift) stay fail-OPEN."""

    def _garble(self, root, content):
        zd = os.path.join(root, ".zaude")
        os.makedirs(zd, exist_ok=True)
        with open(os.path.join(zd, "project.json"), "w", encoding="utf-8") as f:
            f.write(content)
        return zd

    def _hook(self, cwd, disabled=False):
        env = dict(os.environ)
        env.pop("ZAUDE_DISABLE", None)
        if disabled:
            env["ZAUDE_DISABLE"] = "1"
        p = subprocess.run([sys.executable, os.path.join(VROOT, "zhook.py"), "pre_tool_use"],
                           input=json.dumps({"cwd": cwd, "tool_name": "Edit",
                                             "tool_input": {"file_path": os.path.join(cwd, "src", "a.ts")}}).encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        return p.returncode, p.stdout.decode().strip()

    # ---- the tri-state loader (single read; no TOCTOU) ----
    def test_load_marker_valid(self):
        write_project(self.tmp, "enforce")
        self.assertIsInstance(paths._load_marker(self.root), dict)

    def test_load_marker_absent_is_none(self):
        self.assertIsNone(paths._load_marker(self.root))                 # no .zaude at all

    def test_load_marker_garbled_is_broken(self):
        self._garble(self.tmp, "{not json at all")
        m = paths._load_marker(self.root)
        self.assertIsInstance(m, paths._Broken)
        self.assertEqual(m.reason, "badjson")

    def test_load_marker_empty_is_broken(self):
        self._garble(self.tmp, "   \n")
        self.assertEqual(getattr(paths._load_marker(self.root), "reason", None), "empty")

    def test_load_marker_directory_is_broken(self):
        os.makedirs(os.path.join(self.tmp, ".zaude", "project.json"))    # a DIR where a file belongs
        self.assertIsInstance(paths._load_marker(self.root), paths._Broken)

    def test_load_marker_nan_is_broken(self):
        # NaN/Infinity parse under default json but are NOT standard JSON -> garbled, fail closed.
        self._garble(self.tmp, "NaN")
        self.assertEqual(getattr(paths._load_marker(self.root), "reason", None), "badjson")

    def test_load_marker_dangling_symlink_is_broken(self):
        # a present-but-unusable marker (symlink to a missing target) must FAIL CLOSED, not open
        # like a truly-absent marker. [codex review CRITICAL]
        zd = os.path.join(self.tmp, ".zaude")
        os.makedirs(zd, exist_ok=True)
        link = os.path.join(zd, "project.json")
        try:
            os.symlink(os.path.join(self.tmp, "no_such_target.json"), link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("symlink unavailable / requires privilege")
        self.assertIsInstance(paths._load_marker(self.root), paths._Broken)
        self.assertEqual(paths.resolve(self.root)["status"], "broken")

    def test_clone_with_foreign_root_is_fail_open(self):
        # a fresh `git clone` carries the original machine's absolute project_root -> parses but
        # does not claim this dir -> NONE (fail open), never broken.
        write_project(self.tmp, "enforce", project_root="/some/other/machine/path")
        self.assertIsNone(paths._load_marker(self.root))
        self.assertEqual(paths.resolve(self.root)["status"], "none")

    def test_foreign_tool_marker_is_fail_open(self):
        self._garble(self.tmp, json.dumps({"some_other_tool": True}))    # valid JSON, not ours
        self.assertIsNone(paths._load_marker(self.root))

    # ---- resolve() tri-state + walk semantics ----
    def test_resolve_broken(self):
        self._garble(self.tmp, "{bad")
        r = paths.resolve(self.root)
        self.assertEqual(r["status"], "broken")
        self.assertEqual(paths._real(r["broken_root"]), self.root)

    def test_resolve_stops_at_broken_child_not_parent(self):
        # parent is a VALID onboarded project; a child with a CORRUPT marker must NOT silently
        # bind to the parent's .zaude — resolve stops at the broken child.
        write_project(self.tmp, "enforce")
        child = os.path.join(self.tmp, "sub")
        self._garble(child, "{garbled")
        self.assertEqual(paths.resolve(child)["status"], "broken")
        self.assertIsNone(paths.find_project(child))                     # CLI back-compat: not-onboarded

    def test_find_project_backcompat_broken_is_none(self):
        self._garble(self.tmp, "{bad")
        self.assertIsNone(paths.find_project(self.root))                 # CLI sees broken as not-onboarded

    # ---- the hook actually fails closed ----
    def test_hook_denies_on_broken_marker(self):
        self._garble(self.tmp, "{corrupt")
        rc, out = self._hook(self.tmp)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_kill_switch_escapes_broken_marker(self):
        self._garble(self.tmp, "{corrupt")
        self.assertEqual(self._hook(self.tmp, disabled=True), (0, ""))   # ZAUDE_DISABLE=1 bypass

    def test_hook_allows_foreign_marker(self):
        self._garble(self.tmp, json.dumps({"some_other_tool": True}))    # parses, not ours -> open
        self.assertEqual(self._hook(self.tmp), (0, ""))

    # ---- the preflight audit CLI ----
    def test_scan_markers_reports_broken(self):
        self._garble(os.path.join(self.tmp, "proj_a"), "{bad")
        write_project(os.path.join(self.tmp, "proj_b"), "shadow")
        p = subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "scan-markers", self.tmp],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(p.returncode, 1)                               # at least one BROKEN -> rc 1
        self.assertIn("BROKEN", p.stdout)
        self.assertIn("ok", p.stdout)


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


class CodexGracefulTests(TmpCase):
    """Locks the GRACEFUL-codex contract: best-effort, NEVER a gate. The critical regression
    locks are the ones that prove the rejected fail-closed behaviour can't return — codex never
    changes an exit code; it only changes the trace record and stderr text."""
    import argparse as _ap

    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _seat(self, tier, **kw):
        """Call cli._codex_review_seat in-process with a fake args + monkeypatched probe."""
        import cli
        zd = os.path.join(self.tmp, ".zaude")
        os.makedirs(zd, exist_ok=True)
        args = self._ap.Namespace(codex=kw.get("codex", "auto"),
                                  codex_verdict=kw.get("codex_verdict"),
                                  codex_summary=kw.get("codex_summary", ""),
                                  codex_error=kw.get("codex_error"),
                                  codex_retry_at=kw.get("codex_retry_at"))
        if "probe" in kw:
            import lib.codex as cx
            orig = cx.probe
            cx.probe = lambda *a, **k: kw["probe"]
            try:
                return cli._codex_review_seat(zd, args, tier)
            finally:
                cx.probe = orig
        return cli._codex_review_seat(zd, args, tier)

    # ---- seat logic (in-process, deterministic, cross-platform) ----
    def test_low_risk_skips_codex(self):
        s = self._seat("T1")
        self.assertEqual((s["outcome"], s["reason"]), ("skipped", "low_risk"))

    def test_unclassified_skips_codex(self):
        s = self._seat(None)
        self.assertEqual(s["outcome"], "skipped")

    def test_driver_verdict_recorded_as_used(self):
        s = self._seat("T4", codex_verdict="fail", codex_summary="found X")
        self.assertEqual((s["outcome"], s["verdict"]), ("used", "fail"))
        self.assertTrue(s["enforced"])

    def test_off_overrides_verdict(self):
        # an explicit --codex off MUST win over a stray --codex-verdict (honest skip, not 'used')
        s = self._seat("T4", codex="off", codex_verdict="pass")
        self.assertEqual((s["outcome"], s["reason"]), ("skipped", "off"))
        self.assertFalse(s["enforced"])

    def test_enforced_only_on_used(self):
        self.assertTrue(self._seat("T4", codex_verdict="pass")["enforced"])
        self.assertFalse(self._seat("T1")["enforced"])
        self.assertFalse(self._seat("T4", probe={"status": "missing", "detail": "x"})["enforced"])

    def test_no_credit_wired_via_error_arms_backoff(self):
        # the driver reports codex's quota/rate-limit error -> seat=no_credit AND backoff armed so
        # codex auto-resumes only after the retry window (the user's explicit requirement).
        import lib.codex as cx
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True)
        s = self._seat("T4", codex_error="Error: 429 rate limit exceeded",
                       codex_retry_at="9999999999")
        self.assertEqual(s["outcome"], "no_credit")
        self.assertEqual(s["retry_at"], 9999999999.0)
        self.assertFalse(cx.due_now(cx.read_status(zd)))   # in backoff -> not due yet

    def test_ready_but_no_verdict_is_nudge_not_block(self):
        s = self._seat("T4", probe={"status": "ready", "version": "1.0", "auth_source": "env",
                                    "detail": "tok"})
        self.assertEqual((s["outcome"], s["reason"]), ("skipped", "available_not_run"))
        self.assertFalse(s["enforced"])   # the ONE visible gap — still proceeds

    def test_missing_codex_records_unavailable(self):
        s = self._seat("T4", probe={"status": "missing", "version": None, "auth_source": None,
                                    "detail": "no codex"})
        self.assertEqual((s["outcome"], s["reason"]), ("unavailable", "missing"))

    def test_present_noauth_records_unavailable(self):
        s = self._seat("T3", probe={"status": "present_noauth", "version": "1.0",
                                    "auth_source": None, "detail": "no login"})
        self.assertEqual((s["outcome"], s["reason"]), ("unavailable", "present_noauth"))

    def test_no_credit_backoff_honored_without_probe(self):
        import lib.codex as cx
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True)
        cx.note_no_credit(zd, "quota", time.time() + 3600)   # blocked, future reset
        # probe must NOT be consulted while in backoff -> patch it to blow up if called
        called = {"n": 0}
        orig = cx.probe; cx.probe = lambda *a, **k: called.__setitem__("n", 1) or {"status": "ready"}
        try:
            s = self._seat("T4")
        finally:
            cx.probe = orig
        self.assertEqual(s["outcome"], "no_credit")
        self.assertEqual(called["n"], 0)

    # ---- codex.py pure helpers ----
    def test_due_now(self):
        import lib.codex as cx
        self.assertTrue(cx.due_now({"retry": {"blocked": False}}))
        self.assertTrue(cx.due_now({"retry": {"blocked": True, "retry_at": None}}))
        self.assertTrue(cx.due_now({"retry": {"blocked": True, "retry_at": time.time() - 10}}))
        self.assertFalse(cx.due_now({"retry": {"blocked": True, "retry_at": time.time() + 999}}))

    def test_classify_error(self):
        import lib.codex as cx
        self.assertEqual(cx.classify_error(1, "Error: out of credit")["reason"], cx.QUOTA)
        self.assertEqual(cx.classify_error(1, "429 rate limit exceeded")["reason"], cx.RATE_LIMIT)
        self.assertEqual(cx.classify_error(1, "401 unauthorized")["reason"], cx.AUTH)
        r = cx.classify_error(1, "rate limit; retry-after: 120s", now=1000.0)
        self.assertEqual(r["retry_at"], 1120.0)

    def test_token_symlink_refused(self):
        import lib.codex as cx
        # a symlink at the secret path must be refused by _secret_ok (mirrors the PAT contract)
        if not hasattr(os, "symlink"):
            self.skipTest("no symlink")
        target = os.path.join(self.tmp, "evil"); open(target, "w").write("tok")
        link = os.path.join(self.tmp, "codexlink")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not permitted")
        orig = cx._SECRET_FILE
        cx._SECRET_FILE = link
        try:
            self.assertFalse(cx._secret_ok())
        finally:
            cx._SECRET_FILE = orig

    # ---- integration: the anti-fail-closed locks ----
    def test_codex_absence_never_blocks_ship(self):
        """Full T4 lifecycle; codex recorded unavailable at /review -> /ship STILL proceeds."""
        import cli
        self.assertEqual(self._cli("init", "--text", "x", "--mode", "enforce").returncode, 0)
        for cmd in (["clarify", "--acceptance", "x"], ["prioritize", "--decision", "n"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T4"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "t", "--exit", "0"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)
        # /review in-process with codex forced MISSING
        import lib.codex as cx
        orig = cx.probe
        cx.probe = lambda *a, **k: {"status": "missing", "version": None, "auth_source": None,
                                    "detail": "absent", "checked_at": time.time()}
        try:
            rc = cli.cmd_review(self._ap.Namespace(path=self.tmp, summary="", unresolved="0",
                                                   codex="auto", codex_verdict=None, codex_summary=""))
        finally:
            cx.probe = orig
        self.assertEqual(rc, 0)
        ledger = json.load(open(os.path.join(self.tmp, ".zaude", "artifacts",
                                             "review-ledger.json"), encoding="utf-8"))
        self.assertEqual(ledger["review_seats"]["codex"]["outcome"], "unavailable")
        for cmd in (["verify"], ["shippable"], ["ship", "--deploy-id", "d1"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)   # absence NEVER blocks ship

    def test_doctor_exit0_regardless_of_codex(self):
        """doctor must NEVER fail because of codex state (anti-fail-closed lock)."""
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertEqual(self._cli("doctor").returncode, 0)

    def test_codex_status_command_exits_0(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        r = self._cli("codex", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertIn("status", json.loads(r.stdout))


class AgentPresenceTests(TmpCase):
    """Finding #4.1 — required-agent visibility. Uses SYNTHETIC agent names so the real
    ~/.claude/agents on the dev machine can't make the assertions flaky."""
    import argparse as _ap

    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_check_present_and_missing(self):
        import lib.agents as ag
        d = os.path.join(self.tmp, ".claude", "agents")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "zztest-present-abc.md"), "w").write("x")
        r = ag.check(self.tmp, required=["zztest-present-abc", "zztest-missing-xyz"])
        self.assertEqual(r["present"], ["zztest-present-abc"])
        self.assertEqual(r["missing"], ["zztest-missing-xyz"])

    def test_discover_never_raises_on_absent_dirs(self):
        import lib.agents as ag
        # a project with no .claude/agents must not raise — just contributes nothing
        self.assertIsInstance(ag.discover_installed(self.tmp), set)

    def test_doctor_exit0_even_with_missing_agents(self):
        # advisory only — missing required agents must NOT flip doctor's exit code
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertEqual(self._cli("doctor").returncode, 0)

    def test_agents_command_exits_0(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        r = self._cli("agents", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertIn("missing", json.loads(r.stdout))

    def test_required_agents_match_policy(self):
        # drift-lock (codex LOW): the runtime REQUIRED_AGENTS must equal policy.json's documented
        # dispatch.required_agents, so the two can't silently diverge.
        import lib.agents as ag
        with open(_POLICY, encoding="utf-8") as f:
            pol = json.load(f)
        self.assertEqual(ag.REQUIRED_AGENTS, pol["dispatch"]["required_agents"])

    def test_catalog_covers_every_required_agent(self):
        # the researched source catalog must map EVERY required role, so `zaude agents` can always
        # point a missing one at a vetted source. [agent refresh]
        import lib.agents as ag
        for name in ag.REQUIRED_AGENTS:
            self.assertIn(name, ag.CATALOG, name)

    def test_guidance_is_actionable(self):
        import lib.agents as ag
        g = ag.guidance(["architect-review", "totally-unknown-agent"])
        names = {n: (role, src, slug) for (n, role, src, slug) in g}
        self.assertEqual(names["architect-review"][2], "architect-reviewer")   # upstream slug
        self.assertTrue(names["architect-review"][1])                          # has a source repo
        self.assertIn("totally-unknown-agent", names)                          # unknowns still listed

    def test_sources_ranked_primary_spans_codex(self):
        import lib.agents as ag
        self.assertGreaterEqual(len(ag.SOURCES), 2)
        self.assertTrue(ag.SOURCES[0][3])                 # top-ranked source supports Codex (cx flag)
        self.assertIn("/", ag.PRIMARY_SOURCE)             # an owner/repo

    def test_agents_json_carries_sources(self):
        # `sources` is ALWAYS emitted (machine-independent). `guidance` is keyed on what's missing,
        # which varies by machine (the dev box already has the agents), so it's unit-tested above.
        self._cli("init", "--text", "x", "--mode", "enforce")
        out = json.loads(self._cli("agents", "--json").stdout)
        self.assertTrue(out["sources"])
        self.assertTrue(out["sources"][0]["codex"])       # top source spans Codex
        self.assertIn("guidance", out)                    # key present (may be [] if nothing missing)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class FindingsBatch2Tests(TmpCase):
    """Findings #1 (autonomous /next), #3.1 (PM staleness signal), #7 (design agent)."""
    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_next_points_to_clarify_at_intake(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        r = self._cli("next", "--json")
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertEqual(d["next_command"], "/clarify")
        self.assertFalse(d["dod_reached"])

    def test_next_map_endpoints(self):
        import cli
        self.assertIsNone(cli._NEXT_COMMAND["Closed"])
        self.assertEqual(cli._NEXT_COMMAND["Tested"], "/review")

    def test_pm_unsynced_counts_board_rows_after_last_sync(self):
        import cli
        rows = [{"kind": "pm_intake"}, {"kind": "pm_synced"},
                {"kind": "transition", "from": "a", "to": "b"}, {"kind": "pm_promote"}]
        self.assertEqual(cli._pm_unsynced(rows), 2)
        self.assertEqual(cli._pm_unsynced(rows + [{"kind": "pm_synced"}]), 0)
        self.assertEqual(cli._pm_unsynced([{"kind": "waiver"}, {"kind": "pm_synced"}]), 0)

    def test_design_agent_in_policy(self):
        with open(_POLICY, encoding="utf-8") as f:
            pol = json.load(f)
        self.assertIn("ui-design-implementer", [a["name"] for a in pol["agents"]])


class FindingsBatch3Tests(TmpCase):
    """Findings #2 (vault-push), #6 (runner emit), #3.3 (native sub-issues) — all offline-tested."""
    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # ---- #2 vault-push (offline: push to a local bare repo, no network/token) ----
    def test_vault_push_to_local_bare_remote(self):
        bare = os.path.join(self.tmp, "vault-remote.git")
        subprocess.run(["git", "init", "--bare", "-q", bare], check=True)
        self._cli("onboard", "--slug", "proj", "--text", "x")          # creates root/vault/proj/
        r = self._cli("vault-push", "--remote", bare)
        self.assertEqual(r.returncode, 0, r.stderr)
        ls = subprocess.run(["git", "ls-remote", "--heads", bare], capture_output=True, text=True)
        self.assertIn("refs/heads/main", ls.stdout)                    # vault content landed
        # parent .gitignore now ignores the nested vault repo
        self.assertIn("vault/", open(os.path.join(self.tmp, ".gitignore"), encoding="utf-8").read())

    def test_vault_push_no_remote_is_advisory(self):
        self._cli("onboard", "--slug", "proj", "--text", "x")
        r = self._cli("vault-push")
        self.assertEqual(r.returncode, 0)
        self.assertIn("no remote configured", r.stdout)

    # ---- #6 runner emit ----
    def test_runner_github_emits_hosted_workflow(self):
        self._cli("onboard", "--slug", "p", "--text", "x")
        r = self._cli("runner", "--mode", "github")
        self.assertEqual(r.returncode, 0)
        wf = open(os.path.join(self.tmp, ".github", "workflows", "zaude-ci.yml"), encoding="utf-8").read()
        self.assertIn("ubuntu-latest", wf)
        self.assertIn("permissions:", wf)

    def test_runner_self_hosted_emits_setup_script(self):
        self._cli("onboard", "--slug", "p", "--text", "x")
        r = self._cli("runner", "--mode", "self-hosted", "--repo-url", "https://github.com/o/r")
        self.assertEqual(r.returncode, 0)
        wf = open(os.path.join(self.tmp, ".github", "workflows", "zaude-ci.yml"), encoding="utf-8").read()
        self.assertIn("self-hosted", wf)
        body = open(os.path.join(self.tmp, ".github", "runner-setup.sh"), encoding="utf-8").read()
        self.assertIn("GITHUB_RUNNER_TOKEN", body)        # env-var token, not a stored secret
        self.assertNotIn("2.319.1", body)                 # not a stale pinned version
        self.assertIn("releases/latest", body)            # discovers latest at runtime

    # ---- #3.3 native sub-issues (mock rest; offline) ----
    def test_link_subissues_posts_child_to_parent(self):
        import lib.pm_github as pg
        calls = []
        def fake(method, path, payload=None):
            calls.append((method, path, payload))
            return (200, []) if method == "GET" else (201, {})
        orig = pg.rest; pg.rest = fake
        try:
            board = {"items": {"W1": {"type": "feature"},
                               "W1-1": {"type": "tech-task", "parent": "W1"}}}
            mapping = {"W1": {"number": 10, "id": 1000}, "W1-1": {"number": 11, "id": 1001}}
            linked = pg.link_subissues("o", "r", board, mapping)
        finally:
            pg.rest = orig
        self.assertEqual(linked, 1)
        post = [c for c in calls if c[0] == "POST"][0]
        self.assertIn("/issues/10/sub_issues", post[1])    # POST to the PARENT number
        self.assertEqual(post[2], {"sub_issue_id": 1001})  # child REST id, not number

    def test_link_subissues_idempotent_and_never_raises(self):
        import lib.pm_github as pg
        def fake(method, path, payload=None):
            if method == "GET":
                return 200, [{"id": 1001}]                 # already linked
            raise RuntimeError("should not POST when already linked")
        orig = pg.rest; pg.rest = fake
        try:
            board = {"items": {"W1": {"type": "feature"}, "W1-1": {"type": "bug", "parent": "W1"}}}
            mapping = {"W1": {"number": 10, "id": 1000}, "W1-1": {"number": 11, "id": 1001}}
            self.assertEqual(pg.link_subissues("o", "r", board, mapping), 0)   # skipped
        finally:
            pg.rest = orig

    def test_vault_push_never_logs_credentialed_remote(self):
        # codex-HIGH regression: a token-bearing remote URL must NEVER appear in stdout/stderr
        self._cli("onboard", "--slug", "p", "--text", "x")
        r = self._cli("vault-push", "--remote",
                      "https://x-access-token:SECRETTOKEN123@github.com/o/r.git")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("SECRETTOKEN123", r.stdout + r.stderr)


class IntentRouterTests(TmpCase):
    """Intent detection (architecture review headline). The SAFETY MODEL is the critical lock:
    a destructive command is NEVER 'auto', and ambiguous text never routes confidently."""
    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_safe_request_routes_auto(self):
        import lib.router as r
        res = r.route("where am i in the workflow")
        self.assertEqual(res["command"], "status")
        self.assertEqual(res["mode"], "auto")

    def test_ship_is_always_confirm_never_auto(self):
        import lib.router as r
        res = r.route("ship it to production now", current_state="Shippable")
        self.assertEqual(res["command"], "ship")
        self.assertEqual(res["mode"], "confirm")   # destructive -> confirm regardless of confidence
        self.assertNotEqual(res["mode"], "auto")

    def test_destructive_without_explicit_verb_is_penalized(self):
        import lib.router as r
        # "clean up the work" must NOT confidently route to a destructive command like /close
        res = r.route("clean up the work a bit")
        self.assertNotEqual(res.get("command"), "close")

    def test_state_incompatible_command_is_blocked(self):
        import lib.router as r
        res = r.route("approve it", current_state="Intake")     # approve needs RiskClassified
        if res["command"] == "approve":
            self.assertTrue(res["blocked_by"])

    def test_ambiguous_text_is_ambiguous(self):
        import lib.router as r
        res = r.route("hmm ok then")
        self.assertIn(res["mode"], ("ambiguous",))

    def test_router_never_raises_on_garbage(self):
        import lib.router as r
        for t in (None, "", "🙂🙂🙂", "a" * 5000):
            self.assertIn("mode", r.route(t))

    def test_route_command_exits_0(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        out = self._cli("route", "what should i do next", "--json")
        self.assertEqual(out.returncode, 0)
        self.assertIn("command", json.loads(out.stdout))


class PersonaTests(TmpCase):
    """Operator-learning persona — the 'manage' policy is the critical part: tiered promotion,
    recency decay, drift, privacy, robustness (codex-hardened through 4 review rounds)."""
    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _zd(self):
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True); return zd

    def test_belief_confirmed_only_after_reinforcement(self):
        import lib.persona as p
        zd = self._zd()
        p.promote(zd, "preference", "prefers quality over speed", source="op")
        self.assertEqual(p.brief(zd), "")
        p.promote(zd, "preference", "prefers quality over speed always", source="op")
        self.assertIn("quality", p.brief(zd))

    def test_promote_reinforces_near_match_not_duplicate(self):
        import lib.persona as p
        zd = self._zd()
        p.promote(zd, "rule", "never overwrite user data")
        p.promote(zd, "rule", "never overwrite the user data")
        bs = p.beliefs(zd)
        self.assertEqual(len(bs), 1)
        self.assertEqual(bs[0]["reinforcement"], 2)

    def test_recency_decay(self):
        import lib.persona as p
        zd = self._zd()
        p.promote(zd, "rule", "run codex in the review chain", now=1000.0)
        p.promote(zd, "rule", "run codex in the review chain", now=1000.0)
        fresh = p.beliefs(zd, now=1000.0)[0]["confidence"]
        stale = p.beliefs(zd, now=1000.0 + 200 * 86400)[0]["confidence"]
        self.assertGreater(fresh, stale)
        self.assertGreater(stale, 0)

    def test_drift_flagged(self):
        import lib.persona as p
        zd = self._zd()
        p.promote(zd, "risk_posture", "always run the full review panel")
        p.promote(zd, "risk_posture", "always run the full review panel")
        res = p.promote(zd, "risk_posture", "always skip the review panel")
        self.assertTrue(res.get("drift")); self.assertTrue(res.get("conflicts"))

    def test_forget(self):
        import lib.persona as p
        zd = self._zd()
        b = p.promote(zd, "preference", "likes scannable bullet points")
        self.assertTrue(p.forget(zd, b["id"])); self.assertEqual(p.beliefs(zd), [])

    def test_never_raises_on_garbage(self):
        import lib.persona as p
        zd = self._zd()
        for t in (None, "", "x" * 5000):
            p.observe(zd, "weird-kind", t)
        self.assertIsInstance(p.brief(zd), str)

    def test_persona_command_exits_0(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertEqual(self._cli("persona").returncode, 0)
        self.assertEqual(self._cli("persona", "--promote", "quality over speed",
                                   "--category", "preference").returncode, 0)
        r = self._cli("persona", "--json")
        self.assertEqual(r.returncode, 0); self.assertIn("beliefs", json.loads(r.stdout))

    def test_corrupted_profile_never_raises(self):
        import lib.persona as p
        zd = self._zd(); os.makedirs(os.path.join(zd, "persona"), exist_ok=True)
        open(os.path.join(zd, "persona", "profile.json"), "w", encoding="utf-8").write(
            '{"schema":1,"beliefs":["junk",{"reinforcement":"x","last_seen":"bad","statement":"ok rule"}]}')
        self.assertIsInstance(p.brief(zd), str); self.assertIsInstance(p.beliefs(zd), list)
        self.assertIn("id", p.promote(zd, "rule", "another rule"))

    def test_secret_is_redacted_before_persist(self):
        import lib.persona as p
        zd = self._zd()
        tok = "ghp_" + "A" * 36
        p.promote(zd, "rule", "token is " + tok)
        blob = open(os.path.join(zd, "persona", "profile.json"), encoding="utf-8").read()
        self.assertNotIn(tok, blob); self.assertIn("redacted", blob)

    def test_belief_id_not_reused_after_forget(self):
        import lib.persona as p
        zd = self._zd()
        b1 = p.promote(zd, "preference", "first one"); b2 = p.promote(zd, "preference", "second one two")
        p.forget(zd, b2["id"])
        b3 = p.promote(zd, "preference", "third one three four")
        self.assertNotEqual(b3["id"], b1["id"]); self.assertNotEqual(b3["id"], b2["id"])

    def test_short_restatement_reinforces(self):
        import lib.persona as p
        zd = self._zd()
        p.promote(zd, "rule", "use pytest"); p.promote(zd, "rule", "always use pytest")
        self.assertEqual(len(p.beliefs(zd)), 1)

    def test_nonlist_beliefs_and_huge_profile_never_crash_and_bounded(self):
        import lib.persona as p, json as _j
        zd = self._zd(); os.makedirs(os.path.join(zd, "persona"), exist_ok=True)
        pf = os.path.join(zd, "persona", "profile.json")
        open(pf, "w", encoding="utf-8").write('{"schema":1,"beliefs":1}')
        self.assertIsInstance(p.brief(zd), str); self.assertEqual(p.beliefs(zd), [])
        big = {"schema": 1, "beliefs": [{"id": "B%d" % i, "category": "preference",
               "statement": "pref number %d here" % i, "reinforcement": 5,
               "first_seen": 1000.0, "last_seen": 2.0e9} for i in range(5000)]}
        open(pf, "w", encoding="utf-8").write(_j.dumps(big))
        self.assertLessEqual(len(p.beliefs(zd)), p.MAX_PER_CATEGORY)

    def test_corrupt_belief_id_is_not_leaked(self):
        import lib.persona as pp
        zd = self._zd(); os.makedirs(os.path.join(zd, "persona"), exist_ok=True)
        secret_id = "sk-" + "Z" * 30
        open(os.path.join(zd, "persona", "profile.json"), "w", encoding="utf-8").write(
            '{"schema":1,"beliefs":[{"id":"%s","category":"rule","statement":"use pytest","reinforcement":3}]}' % secret_id)
        bs = pp.beliefs(zd)
        self.assertTrue(bs); self.assertNotEqual(bs[0]["id"], secret_id)
        self.assertRegex(bs[0]["id"], r"^B\d+$")


class CollectiveMemoryTests(TmpCase):
    """Collective-memory recall — hardened from the start (redact, bounded, robust, private)."""
    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _zd(self):
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True); return zd

    def test_recall_ranks_relevant_first(self):
        import lib.memory as m
        zd = self._zd()
        m.remember(zd, "always run codex in the review chain before shipping", tags=["review"])
        m.remember(zd, "the deploy proxy uses the X-Proxy-Pass header", tags=["infra"])
        m.remember(zd, "prefer scannable bullet points in reports")
        hits = m.recall(zd, "how do we do code review with codex", k=3)
        self.assertTrue(hits)
        self.assertIn("codex", hits[0]["text"])

    def test_recall_empty_when_no_match(self):
        import lib.memory as m
        zd = self._zd()
        m.remember(zd, "infrastructure note about nginx")
        self.assertEqual(m.recall(zd, "quantum chromodynamics"), [])

    def test_secret_redacted_on_store_and_load(self):
        import lib.memory as m
        zd = self._zd()
        tok = "ghp_" + "B" * 36
        m.remember(zd, "the token is " + tok + " keep it safe")
        blob = open(os.path.join(zd, "memory", "entries.jsonl"), encoding="utf-8").read()
        self.assertNotIn(tok, blob); self.assertIn("redacted", blob)
        # also redacted on load even if a raw token was injected into the file
        with open(os.path.join(zd, "memory", "entries.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"text":"leak ' + tok + '","tags":[],"ts":1.0}\n')
        for e in m._load(zd):
            self.assertNotIn(tok, e["text"])

    def test_corrupt_line_skipped_never_raises(self):
        import lib.memory as m
        zd = self._zd(); os.makedirs(os.path.join(zd, "memory"), exist_ok=True)
        with open(os.path.join(zd, "memory", "entries.jsonl"), "w", encoding="utf-8") as f:
            f.write("not json\n{\"text\":\"good one about pytest\",\"ts\":1.0}\n{\"nope\":1}\n")
        self.assertIsInstance(m.recall(zd, "pytest"), list)
        self.assertTrue(any("pytest" in h["text"] for h in m.recall(zd, "pytest")))

    def test_never_raises_on_garbage(self):
        import lib.memory as m
        zd = self._zd()
        for t in (None, "", "x" * 9000):
            m.remember(zd, t)
        self.assertIsInstance(m.recall(zd, None), list)
        self.assertIsInstance(m.recall(zd, "x"), list)

    def test_remember_recall_commands_exit_0(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertEqual(self._cli("remember", "lesson: never overwrite prod user data",
                                   "--tags", "prod,safety").returncode, 0)
        r = self._cli("recall", "prod user data", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(any("overwrite" in h["text"] for h in json.loads(r.stdout)))

    def test_recall_k_zero_returns_empty(self):
        import lib.memory as m
        zd = self._zd(); m.remember(zd, "something about pytest and coverage")
        self.assertEqual(m.recall(zd, "pytest", k=0), [])
        self.assertEqual(len(m.recall(zd, "pytest", k=1)), 1)

    def test_load_is_byte_bounded_on_oversized_file(self):
        import lib.memory as m
        zd = self._zd(); os.makedirs(os.path.join(zd, "memory"), exist_ok=True)
        p = os.path.join(zd, "memory", "entries.jsonl")
        # write well over the tail budget; load must stay bounded + still recall
        with open(p, "w", encoding="utf-8") as f:
            for i in range(20000):
                f.write('{"text":"entry number %d about widgets","tags":[],"ts":%d.0}\n' % (i, i))
        ents = m._load(zd)
        self.assertLessEqual(len(ents), m.MAX_ENTRIES)        # never the full 20000
        self.assertIsInstance(m.recall(zd, "widgets", k=3), list)


class VaultProjectionTests(TmpCase):
    """`zaude vault-sync` projects the SIGNED TRACE into the human-readable vault: current-state.md
    regenerated (trace-anchored) + decisions.md append-only + idempotent. [vault upgrade]"""

    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _full_to_risk(self):
        self.assertEqual(self._cli("onboard", "--slug", "demo", "--text", "build a thing").returncode, 0)
        for cmd in (["clarify", "--acceptance", "works"],
                    ["prioritize", "--decision", "ship security first"],
                    ["plan", "--steps", "a,b"],
                    ["design", "--approach", "tri-state resolver", "--decision", "D7"],
                    ["classify-risk", "--tier", "T3"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)

    def test_vault_sync_projects_state_and_decisions(self):
        self._full_to_risk()
        r = self._cli("vault-sync")
        self.assertEqual(r.returncode, 0, r.stderr)
        cs = open(os.path.join(self.tmp, "vault", "demo", "current-state.md"), encoding="utf-8").read()
        self.assertIn("RiskClassified", cs)          # current lifecycle state
        self.assertIn("zaude-trace-anchor", cs)      # anchored to a trace point
        self.assertIn("T3", cs)                      # risk tier surfaced
        self.assertIn("build a thing", cs)           # in-flight request
        dec = open(os.path.join(self.tmp, "vault", "demo", "decisions.md"), encoding="utf-8").read()
        self.assertIn("[ZD-", dec)
        self.assertIn("ship security first", dec)    # priority decision (permanent decision row)
        self.assertIn("tri-state resolver", dec)     # design decision
        self.assertIn("decision_id: D7", dec)
        self.assertIn("tier=T3", dec)                # risk decision

    def test_vault_sync_idempotent(self):
        self._full_to_risk()
        self._cli("vault-sync")
        dp = os.path.join(self.tmp, "vault", "demo", "decisions.md")
        dec1 = open(dp, encoding="utf-8").read()
        r2 = self._cli("vault-sync")
        self.assertIn("0 decision(s) appended", r2.stdout)   # nothing re-appended
        self.assertEqual(dec1, open(dp, encoding="utf-8").read())   # append-only: no growth/dupes

    def test_vault_unit_decisions_append_only_idempotent(self):
        rows = [{"seq": 0, "kind": "init", "ts": 0},
                {"seq": 1, "kind": "decision", "what": "design", "text": "X", "decision_id": "D1", "ts": 0},
                {"seq": 2, "kind": "risk", "tier": "T4", "ts": 0},
                {"seq": 3, "kind": "waiver", "gate": "g1", "ts": 0}]
        p = os.path.join(self.tmp, "decisions.md")
        self.assertEqual(vault.append_decisions(p, rows, 0)[0], 3)   # decision + risk + waiver
        self.assertEqual(vault.append_decisions(p, rows, 0)[0], 0)   # idempotent: no re-append
        self.assertEqual(open(p, encoding="utf-8").read().count("[ZD-"), 3)

    def test_vault_decision_text_cannot_poison_anchors(self):
        # a decision whose TEXT contains "[ZD-9]" must NOT make a future seq-9 row look already
        # projected (anchor poisoning): brackets are neutralized AND anchors match only at line
        # start, so the real seq-9 row still appends later. [codex review HIGH]
        p = os.path.join(self.tmp, "decisions.md")
        vault.append_decisions(p, [{"seq": 1, "kind": "decision", "what": "design",
                                    "text": "mimic [ZD-9] here", "ts": 0}], 0)
        self.assertNotIn("[ZD-9]", open(p, encoding="utf-8").read())   # user text can't mint it
        added, _ = vault.append_decisions(p, [{"seq": 1, "kind": "decision", "text": "a", "ts": 0},
                                              {"seq": 9, "kind": "risk", "tier": "T4", "ts": 0}], 0)
        self.assertEqual(added, 1)                                     # only the real seq-9 appends

    def test_vault_oneline_strips_injection(self):
        out = vault._oneline("a\nb\r\n<!-- x --> [ZD-1]")
        for bad in ("\n", "\r", "<!--", "-->", "[ZD-1]"):
            self.assertNotIn(bad, out)

    def test_vault_sync_missing_vault_dir_fails_cleanly(self):
        self.assertEqual(self._cli("init", "--text", "x", "--mode", "enforce").returncode, 0)
        self.assertEqual(self._cli("vault-sync").returncode, 4)   # no vault/<slug> -> clean refusal
