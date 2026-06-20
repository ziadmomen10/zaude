"""
test_kernel.py (v0.2.0) — locks the hardened kernel's properties: tamper-evident trace,
validating reducer, the gate set (design/deploy/protect), waivers, fail-open, and the full
lifecycle integration. stdlib unittest. Run: python -m unittest discover -s tests
"""
from _helpers import *  # noqa: F401,F403


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

    def test_protect_vault_projection(self):
        # the trace-projected vault files cannot be hand-edited (the #1 v1->v2 mismatch)
        v = os.path.join(self.tmp, "vault", "myslug")
        for base in ("current-state.md", "decisions.md"):
            d, _, g = self._ev("Approved", "Write", {"file_path": os.path.join(v, base)})
            self.assertEqual((d, g), ("deny", "protect_vault_projection"), base)
        # other vault files are scaffolded-once / hand-maintained, NOT projections -> allowed
        for base in ("spec.md", "CLAUDE.md", "open-questions.md"):
            self.assertEqual(
                self._ev("Approved", "Write", {"file_path": os.path.join(v, base)})[0], "allow", base)
        # a current-state.md OUTSIDE this project's vault/ (e.g. the old vault) is not its projection
        self.assertEqual(
            self._ev("Approved", "Write",
                     {"file_path": os.path.join(self.tmp, "docs", "current-state.md")})[0], "allow")

    def test_protect_vault_projection_waivable(self):
        v = os.path.join(self.tmp, "vault", "s")
        d, _, _ = self._ev("Approved", "Write", {"file_path": os.path.join(v, "current-state.md")},
                           waived=["protect-vault-projection"])
        self.assertEqual(d, "allow-waived")

    def test_protect_vault_projection_bypass_resistance(self):
        v = os.path.join(self.tmp, "vault", "s")
        # every mutating tool is gated (not just Write)
        for tool in ("Edit", "MultiEdit", "NotebookEdit"):
            key = "notebook_path" if tool == "NotebookEdit" else "file_path"
            d, _, g = self._ev("Approved", tool, {key: os.path.join(v, "current-state.md")})
            self.assertEqual((d, g), ("deny", "protect_vault_projection"), tool)
        # filename-normalization tricks still resolve to the protected base
        for trick in ("CURRENT-STATE.MD", "current-state.md.", "current-state.md "):
            self.assertEqual(
                self._ev("Approved", "Write", {"file_path": os.path.join(v, trick)})[0], "deny", trick)
        # nested deeper under vault/ is still inside the boundary
        self.assertEqual(
            self._ev("Approved", "Write",
                     {"file_path": os.path.join(v, "a", "b", "current-state.md")})[0], "deny")
        # a non-mutating tool (Read) must NOT be gated — no over-fire
        self.assertEqual(
            self._ev("Approved", "Read", {"file_path": os.path.join(v, "current-state.md")})[0], "allow")

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

    # ---- finding A: Bash file-writes can no longer silently evade the Edit/Write gates ----
    def _bash(self, current, command, **kw):
        return self._ev(current, "Bash", {"command": command}, **kw)

    def test_bash_write_to_zaude_denied_not_waivable(self):
        d, _, g = self._bash("Approved", "echo x > .zaude/trace.jsonl")
        self.assertEqual((d, g), ("deny", "protect_zaude_bash"))
        # rm of the state dir is the same class
        self.assertEqual(self._bash("Approved", "rm -rf .zaude")[0], "deny")
        # NOT waivable — even a waiver can't unlock a direct .zaude write
        self.assertEqual(self._bash("Approved", "echo x >> .zaude/state.json",
                                    waived=["protect_zaude_bash", "protect-zaude-bash"])[0], "deny")

    def test_bash_read_of_zaude_and_launcher_allowed(self):
        self.assertEqual(self._bash("Approved", "cat .zaude/state.json")[0], "allow")      # read
        self.assertEqual(self._bash("Approved", "grep init .zaude/trace.jsonl")[0], "allow")
        # the kernel's own CLI legitimately writes .zaude and must NEVER be flagged
        self.assertEqual(self._bash("Intake",
                                    'python "$HOME/.zaude/bin/zaude.py" review --unresolved 0')[0],
                         "allow")
        # COPY-OUT reads (.zaude as SOURCE) must NOT be hard-denied by the non-waivable tripwire
        # (codex review: read-capable verbs were dropped to avoid false denies)
        self.assertEqual(self._bash("Approved", "cp .zaude/state.json /tmp/state.json")[0], "allow")
        self.assertEqual(self._bash("Approved", "dd if=.zaude/state of=/tmp/state")[0], "allow")
        self.assertEqual(self._bash("Approved", "cat .zaude/x > /tmp/out")[0], "allow")     # read->write elsewhere

    def test_bash_source_write_gated_at_high_risk(self):
        # T4 pre-approval: a Bash write to source is denied (shares the design-before-impl waiver)
        d, _, g = self._bash("Intake", 'echo "x" > src/app.ts', risk="T4")
        self.assertEqual((d, g), ("deny", "design_before_impl_bash"))
        self.assertEqual(self._bash("Intake", "sed -i 's/a/b/' main.py", risk="T4")[0], "deny")
        # one /waive design-before-impl covers BOTH the Edit and the Bash variant
        self.assertEqual(self._bash("Intake", 'echo x > src/app.ts', risk="T4",
                                    waived=["design-before-impl"])[0], "allow-waived")

    def test_bash_source_write_light_by_default(self):
        # low/unclassified risk codes freely; reads and non-source writes are never gated
        self.assertEqual(self._bash("Intake", 'echo x > src/app.ts')[0], "allow")           # unclassified
        self.assertEqual(self._bash("Intake", 'echo x > src/app.ts', risk="T1")[0], "allow")
        self.assertEqual(self._bash("Approved", 'echo x > src/app.ts', risk="T4")[0], "allow")  # post-approval
        self.assertEqual(self._bash("Intake", 'echo notes > TODO.txt', risk="T4")[0], "allow")  # non-source
        self.assertEqual(self._bash("Intake", "cat src/app.ts", risk="T4")[0], "allow")         # read


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
        self.assertIn("Edit", hb["PreToolUse"]["matcher"])
        self.assertIn("zhook.py", hb["PreToolUse"]["hooks"][0]["command"])
        self.assertIn("UserPromptSubmit", hb)  # P0b: front-door hook is reproducible
        self.assertIn("zhook.py", hb["UserPromptSubmit"]["hooks"][0]["command"])
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

    def test_render_command_body_override(self):
        # an orchestration command (e.g. /zwrap) carries a custom `body`, emitted VERBATIM (braces
        # safe) with the description header + marker, and NOT the thin CLI-wrapper template.
        from lib import generator
        rich = generator.render_command(
            {"name": "x", "cli": "status", "summary": "S", "body": "CUSTOM {body} <ok>"})
        self.assertIn("CUSTOM {body} <ok>", rich)         # verbatim, no .format() on the body
        self.assertIn("description: S", rich)
        self.assertIn(generator.MARKER, rich)
        self.assertNotIn("If unsure of the flags", rich)  # thin-template text must be absent
        # a command WITHOUT a body still uses the thin CLI wrapper.
        thin = generator.render_command({"name": "y", "cli": "status", "summary": "S"})
        self.assertIn("If unsure of the flags", thin)
        # a present-but-blank body must FAIL rather than silently render the thin wrapper.
        with self.assertRaises(ValueError):
            generator.render_command({"name": "z", "cli": "status", "summary": "S", "body": "   "})

    def test_wrap_command_is_trace_anchored(self):
        # the shipped /zwrap must drive the trace-anchored path (vault-sync) and must NOT hand-edit
        # the projected current-state.md — the whole point of the v2 wrap.
        from lib import generator
        out = os.path.join(self.tmp, "gen")
        generator.generate(out_dir=out, policy_path=_POLICY)
        wrap = open(os.path.join(out, "commands", "wrap.md"), encoding="utf-8").read()
        self.assertIn("vault-sync", wrap)
        self.assertIn("source of truth", wrap)
        self.assertNotIn("If unsure of the flags", wrap)  # proves the body override took effect


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
