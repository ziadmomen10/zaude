"""test_features.py (v0.2.0) — the operator-learning + reviewer + PM + findings layers
(codex/opencode seats, persona, memory, intent router, vault projection, agent presence).
Core kernel locks (trace/reducer/gates/hook) live in test_kernel.py. Run: unittest discover.
"""
from _helpers import *  # noqa: F401,F403


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
        # /review in-process with codex forced MISSING. Force opencode MISSING too: this lock is
        # about the codex seat being ABSENT (anti-fail-closed) — on a box where opencode is actually
        # installed it would otherwise trip the (separate) panel-enforcement gate, which is not what
        # this test exercises. Both absent => both 'unavailable' => panel gate silent (correct).
        import lib.codex as cx, lib.opencode as oc
        orig = cx.probe
        oc_orig = oc.probe
        cx.probe = lambda *a, **k: {"status": "missing", "version": None, "auth_source": None,
                                    "detail": "absent", "checked_at": time.time()}
        oc.probe = lambda *a, **k: {"status": oc.MISSING, "version": None, "detail": "absent"}
        try:
            rc = cli.cmd_review(self._ap.Namespace(path=self.tmp, summary="", unresolved="0",
                                                   codex="auto", codex_verdict=None, codex_summary=""))
        finally:
            cx.probe = orig
            oc.probe = oc_orig
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


class OpenCodeGracefulTests(TmpCase):
    """OpenCode is the THIRD best-effort review seat — same graceful contract as codex: never gates,
    never raises, independent retry state. Mirrors CodexGracefulTests on the seat dict (the gate
    invariant is what matters, not stderr text)."""
    import argparse as _ap

    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _seat(self, tier, **kw):
        import cli
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True)
        args = self._ap.Namespace(opencode=kw.get("opencode", "auto"),
                                  opencode_verdict=kw.get("opencode_verdict"),
                                  opencode_summary=kw.get("opencode_summary", ""),
                                  opencode_error=kw.get("opencode_error"),
                                  opencode_retry_at=kw.get("opencode_retry_at"))
        if "probe" in kw:
            import lib.opencode as oc
            orig = oc.probe; oc.probe = lambda *a, **k: kw["probe"]
            try:
                return cli._opencode_review_seat(zd, args, tier)
            finally:
                oc.probe = orig
        return cli._opencode_review_seat(zd, args, tier)

    def test_low_risk_skips(self):
        self.assertEqual(self._seat("T1")["reason"], "low_risk")

    def test_verdict_recorded_used_and_enforced(self):
        s = self._seat("T4", opencode_verdict="concerns", opencode_summary="diverse take")
        self.assertEqual((s["outcome"], s["verdict"]), ("used", "concerns"))
        self.assertTrue(s["enforced"])

    def test_off_overrides_verdict(self):
        s = self._seat("T4", opencode="off", opencode_verdict="pass")
        self.assertEqual((s["outcome"], s["reason"]), ("skipped", "off"))
        self.assertFalse(s["enforced"])

    def test_missing_records_unavailable_not_gate(self):
        s = self._seat("T4", probe={"status": "missing", "version": None, "detail": "no opencode"})
        self.assertEqual((s["outcome"], s["reason"]), ("unavailable", "missing"))
        self.assertFalse(s["enforced"])

    def test_present_noauth_records_unavailable(self):
        s = self._seat("T3", probe={"status": "present_noauth", "version": "1", "detail": "no auth"})
        self.assertEqual((s["outcome"], s["reason"]), ("unavailable", "present_noauth"))

    def test_ready_no_verdict_is_nudge(self):
        s = self._seat("T4", probe={"status": "ready", "version": "1", "detail": "ok"})
        self.assertEqual((s["outcome"], s["reason"]), ("skipped", "available_not_run"))
        self.assertFalse(s["enforced"])

    def test_no_credit_via_error_arms_independent_backoff(self):
        import lib.opencode as oc, lib.codex as cx
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True)
        s = self._seat("T4", opencode_error="429 rate limit", opencode_retry_at="9999999999")
        self.assertEqual(s["outcome"], "no_credit")
        self.assertFalse(oc.due_now(oc.read_status(zd)))      # opencode in backoff
        self.assertTrue(cx.due_now(cx.read_status(zd)))       # codex UNAFFECTED (independent state)

    def test_probe_never_raises(self):
        import lib.opencode as oc
        self.assertIn(oc.probe().get("status"), (oc.MISSING, oc.PRESENT_NOAUTH, oc.READY))

    def test_review_ledger_carries_both_seats_and_opencode_never_gates(self):
        # full chain to Reviewed at T4 -> /review commits (0), the ledger records BOTH seats, and
        # unresolved_critical_high is untouched by either seat. This runs as a real subprocess, so it
        # sees the box's REAL probes; deliberate skip-acks satisfy the (separate) panel-enforcement
        # gate on a box that HAS the seats and are harmless no-ops on a box that doesn't — keeping the
        # invariant under test (a seat never mutates the ship-gate input) environment-independent.
        for cmd in (["init", "--text", "x", "--mode", "enforce"],
                    ["clarify", "--acceptance", "a"], ["prioritize", "--decision", "d"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T4"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "pytest", "--exit", "0"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)
        r = self._cli("review", "--unresolved", "0",
                      "--skip-codex-ack", "n/a for this lock",
                      "--skip-opencode-ack", "n/a for this lock")
        self.assertEqual(r.returncode, 0, r.stderr)           # a recorded seat NEVER fails /review
        led = json.load(open(os.path.join(self.tmp, ".zaude", "artifacts", "review-ledger.json"),
                             encoding="utf-8"))
        self.assertIn("codex", led["review_seats"])
        self.assertIn("opencode", led["review_seats"])        # the third seat is recorded
        self.assertEqual(led["unresolved_critical_high"], 0)  # no seat mutated the gate input

    def test_opencode_status_command_exits_0(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        r = self._cli("opencode", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertIn("status", json.loads(r.stdout))


class AdaptiveFlowsTests(TmpCase):
    """Task-typed adaptive flows (Approach B, engine-level collapse). The invariants under lock:
    n/a stages are recorded HONESTLY (never silently skipped), every flow transition is a legal
    linear can_transition, the {"kind":"flow"} marker is ignored by the reducer, build is
    behavior-identical to today, Reviewed-terminal flows NEVER issue a release token, the evidence
    gate survives for Released-terminal flows, and an OLD (no-flow) trace replays unchanged."""
    import argparse as _ap

    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _rows(self):
        return trace.read_trace(os.path.join(self.tmp, ".zaude"), self.root, verify=True)

    def _artifact(self, name):
        with open(os.path.join(self.tmp, ".zaude", "artifacts", name), encoding="utf-8") as f:
            return json.load(f)

    # ---- bugfix: workable state in ONE command, n/a honesty ----
    def test_bugfix_reaches_workable_state_in_one_command(self):
        self.assertEqual(self._cli("init", "--text", "crash", "--mode", "enforce").returncode, 0)
        r = self._cli("flow", "--type", "bugfix", "--note", "repro: 500 on empty pw")
        self.assertEqual(r.returncode, 0, r.stderr)
        proj = st.reduce(self._rows())
        self.assertEqual(proj["current_state"], "Approved")    # coding is unblocked in one step
        self.assertEqual(proj["risk_tier"], "T1")              # opening recorded the tier

    def test_na_stages_recorded_honestly(self):
        self._cli("init", "--text", "crash", "--mode", "enforce")
        self._cli("flow", "--type", "bugfix", "--note", "x")
        # bugfix marks Prioritized/Planned/Designed n/a -> their artifacts carry {"na": True}
        for art in ("priority.json", "plan.json", "design.json"):
            self.assertEqual(self._artifact(art).get("na"), True, art)
        # an APPLICABLE stage (Clarified=reproduce) is NOT n/a — it carries the real note
        self.assertNotEqual(self._artifact("requirements.json").get("na"), True)
        self.assertEqual(self._artifact("requirements.json").get("note"), "x")
        # the n/a flag is also honest on the transition rows themselves
        na_rows = {r["to"]: r.get("na") for r in self._rows() if r.get("kind") == "transition"}
        self.assertTrue(na_rows["Prioritized"])                # n/a
        self.assertFalse(na_rows["Clarified"])                 # applicable

    def test_flow_marker_ignored_by_reducer(self):
        # the {"kind":"flow"} marker is an UNKNOWN kind to reduce() -> it must not affect the fold,
        # and the projection must equal a reduce() over the SAME rows with the markers stripped.
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._cli("flow", "--type", "bugfix", "--note", "x")
        rows = self._rows()
        self.assertTrue(any(r.get("kind") == "flow" for r in rows))   # marker really is present
        with_marker = st.reduce(rows)
        without = st.reduce([r for r in rows if r.get("kind") != "flow"])
        self.assertEqual(with_marker["current_state"], without["current_state"])
        self.assertEqual(with_marker["artifacts"], without["artifacts"])
        self.assertEqual(with_marker["risk_tier"], without["risk_tier"])

    def test_all_flow_transitions_are_legal_linear(self):
        # a full bugfix run (open + finish) must produce ONLY legal linear can_transition edges, and
        # the validating reducer must accept the whole trace.
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._cli("flow", "--type", "bugfix", "--note", "x")
        self._cli("flow-finish", "--type", "bugfix", "--tested-exit", "0")
        rows = self._rows()
        for r in rows:
            if r.get("kind") == "transition":
                self.assertTrue(st.can_transition(r["from"], r["to"]),
                                "illegal %s->%s" % (r["from"], r["to"]))
        st.reduce(rows)   # validating replay must not raise
        self.assertEqual(st.reduce(rows)["current_state"], "Released")

    def test_trace_verify_passes_after_a_flow_run(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._cli("flow", "--type", "audit", "--note", "scope: auth")
        self._cli("flow-finish", "--type", "audit")
        r = self._cli("trace-verify")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Reviewed", r.stdout)

    # ---- build behavior-identical to today ----
    def test_build_flow_behavior_identical(self):
        # build marks every stage applicable; opening drives Intake->Approved with NO n/a stages,
        # finishing drives Approved->Released with a token — exactly the fast+fast-ship outcome.
        self._cli("init", "--text", "feat", "--mode", "enforce")
        self.assertEqual(self._cli("flow", "--type", "build", "--note", "feat").returncode, 0)
        nas = [r["to"] for r in self._rows() if r.get("kind") == "transition" and r.get("na")]
        self.assertEqual(nas, [])                              # build skips nothing
        self.assertEqual(self._cli("flow-finish", "--type", "build", "--tested-exit", "0").returncode, 0)
        proj = st.reduce(self._rows())
        self.assertEqual(proj["current_state"], "Released")
        self.assertTrue(proj["release_token_active"])          # build is a release flow

    def test_build_flow_dod_matches_today(self):
        # /dod on a build flow reports the same evidence keys (bool, not n/a) and terminal Released.
        self._cli("init", "--text", "feat", "--mode", "enforce")
        self._cli("flow", "--type", "build", "--note", "feat")
        self._cli("flow-finish", "--type", "build", "--tested-exit", "0")
        r = self._cli("dod")
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertTrue(d["dod_met"])
        self.assertEqual(d["terminal"], "Released")
        self.assertIs(d["has_verification_evidence"], True)   # verify applicable -> a real bool

    # ---- audit: NO release token + DoD terminal Reviewed ----
    def test_audit_flow_has_no_release_token_and_dod_terminal_reviewed(self):
        self._cli("init", "--text", "audit auth", "--mode", "enforce")
        self._cli("flow", "--type", "audit", "--note", "scope: sessions")
        r = self._cli("flow-finish", "--type", "audit")
        self.assertEqual(r.returncode, 0, r.stderr)
        proj = st.reduce(self._rows())
        self.assertEqual(proj["current_state"], "Reviewed")    # terminal Reviewed
        self.assertFalse(proj["release_token_active"])         # NO token ever
        # no release_token row was ever appended for an audit flow
        self.assertFalse(any(r.get("kind") == "release_token" for r in self._rows()))
        d = json.loads(self._cli("dod").stdout)
        self.assertEqual(d["terminal"], "Reviewed")
        self.assertTrue(d["dod_met"])                          # done at Reviewed
        self.assertEqual(d["has_verification_evidence"], "n/a")   # Verified is n/a for audit

    def test_research_flow_terminal_reviewed_no_token(self):
        self._cli("init", "--text", "spike", "--mode", "enforce")
        self._cli("flow", "--type", "research", "--note", "question: which cache")
        self.assertEqual(self._cli("flow-finish", "--type", "research").returncode, 0)
        proj = st.reduce(self._rows())
        self.assertEqual(proj["current_state"], "Reviewed")
        self.assertFalse(proj["release_token_active"])

    def test_grooming_flow_terminal_reviewed_no_token(self):
        self._cli("init", "--text", "groom", "--mode", "enforce")
        self._cli("flow", "--type", "grooming", "--note", "intake: Q3 backlog")
        self.assertEqual(self._cli("flow-finish", "--type", "grooming").returncode, 0)
        proj = st.reduce(self._rows())
        self.assertEqual(proj["current_state"], "Reviewed")
        self.assertFalse(proj["release_token_active"])

    # ---- flow-finish keeps the evidence gate for Released flows ----
    def test_flow_finish_evidence_gate_for_released_flows(self):
        self._cli("init", "--text", "bug", "--mode", "enforce")
        self._cli("flow", "--type", "bugfix", "--note", "x")
        # tested-exit 1 must REFUSE (never ship broken) and write NOTHING (state stays Approved)
        r = self._cli("flow-finish", "--type", "bugfix", "--tested-exit", "1")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(st.reduce(self._rows())["current_state"], "Approved")
        # tested-exit 0 ships
        r2 = self._cli("flow-finish", "--type", "bugfix", "--tested-exit", "0")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        proj = st.reduce(self._rows())
        self.assertEqual(proj["current_state"], "Released")
        self.assertTrue(proj["release_token_active"])

    # ---- flow-finish must match the OPENED flow (codex HIGH: no silent flow-type switch) ----
    def test_flow_finish_rejects_type_mismatch(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._cli("flow", "--type", "audit", "--note", "scope")   # audit = no-token, terminal Reviewed
        r = self._cli("flow-finish", "--type", "bugfix", "--tested-exit", "0")  # wrong type
        self.assertEqual(r.returncode, 3)
        proj = st.reduce(self._rows())
        self.assertFalse(proj["release_token_active"])             # no token from the mismatched finish
        self.assertNotEqual(proj["current_state"], "Released")
        self.assertFalse(any(row.get("kind") == "release_token" for row in self._rows()))

    # ---- flow-finish requires an OPENED flow (codex HIGH: no-flow trace must not collapse) ----
    def test_flow_finish_requires_open_flow(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        # no /flow opened -> flow-finish --type build must NOT collapse Intake->Released
        r = self._cli("flow-finish", "--type", "build", "--tested-exit", "0")
        self.assertEqual(r.returncode, 3)
        proj = st.reduce(self._rows())
        self.assertEqual(proj["current_state"], "Intake")        # nothing collapsed
        self.assertFalse(proj["release_token_active"])           # no token issued

    # ---- flow refuses high-risk ----
    def test_flow_refuses_high_risk(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        for tier in ("T3", "T4"):
            r = self._cli("flow", "--type", "bugfix", "--note", "x", "--tier", tier)
            self.assertEqual(r.returncode, 3, tier)
            self.assertEqual(st.reduce(self._rows())["current_state"], "Intake")   # no partial write

    # ---- next is flow-aware (skips n/a) ----
    def test_next_is_flow_aware_skips_na(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._cli("flow", "--type", "audit", "--note", "scope: x")
        # at Approved, the next APPLICABLE audit stage is Implemented (=investigate) -> /implement
        d = json.loads(self._cli("next", "--json").stdout)
        self.assertEqual(d["flow"], "audit")
        self.assertEqual(d["next_command"], "/implement")
        self.assertFalse(d["dod_reached"])
        # drive to the terminal; /next then reports done (terminal-aware, no next command)
        self._cli("flow-finish", "--type", "audit")
        d2 = json.loads(self._cli("next", "--json").stdout)
        self.assertTrue(d2["dod_reached"])
        self.assertIsNone(d2["next_command"])

    def test_next_unit_skips_na_for_research_flow(self):
        import cli
        # research marks Tested applicable, Verified n/a, terminal Reviewed: from Tested, /next must
        # point to /review (skip-stop logic is presentation only; _NEXT_COMMAND is unchanged).
        self.assertEqual(cli._NEXT_COMMAND["Tested"], "/review")
        self.assertEqual(cli._next_command_for_flow("Tested", "research"), ("/review", False))
        # from Reviewed (the research terminal) it is done
        self.assertEqual(cli._next_command_for_flow("Reviewed", "research"), (None, True))

    # ---- unknown flow type => clean refusal ----
    def test_unknown_flow_type_clean_refusal(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        before = len(self._rows())
        r = self._cli("flow", "--type", "nope", "--note", "x")
        self.assertEqual(r.returncode, 3)
        self.assertIn("unknown flow type", r.stderr)
        self.assertEqual(len(self._rows()), before)            # nothing written, no lock fallout
        r2 = self._cli("flow-finish", "--type", "nope")
        self.assertEqual(r2.returncode, 3)
        self.assertEqual(len(self._rows()), before)

    # ---- an OLD linear trace (no flow rows) still replays unchanged ----
    def test_old_linear_trace_replays_unchanged(self):
        # build a trace the classic way: NO /flow command, just the linear lifecycle commands.
        self.assertEqual(self._cli("init", "--text", "x", "--mode", "enforce").returncode, 0)
        for cmd in (["clarify", "--acceptance", "a"], ["prioritize", "--decision", "d"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T1"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "t", "--exit", "0"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)
        rows = self._rows()
        self.assertFalse(any(r.get("kind") == "flow" for r in rows))   # truly no flow rows
        # active_flow defaults to build; /next behaves byte-for-byte as today (no skipping)
        import cli
        self.assertEqual(cli.active_flow(os.path.join(self.tmp, ".zaude"), self.root), "build")
        d = json.loads(self._cli("next", "--json").stdout)
        self.assertEqual(d["current_state"], "Tested")
        self.assertEqual(d["next_command"], "/review")          # exactly _NEXT_COMMAND["Tested"]
        self.assertFalse(d["dod_reached"])
        # trace integrity unaffected
        self.assertEqual(self._cli("trace-verify").returncode, 0)

    def test_old_trace_dod_unchanged_at_released(self):
        # an old linear trace driven all the way to Released: /dod must report terminal Released and
        # bool verification evidence (the exact pre-flow contract).
        self.assertEqual(self._cli("init", "--text", "x", "--mode", "enforce").returncode, 0)
        for cmd in (["clarify", "--acceptance", "a"], ["prioritize", "--decision", "d"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T1"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "t", "--exit", "0"], ["review", "--unresolved", "0"],
                    ["verify"], ["shippable"], ["ship", "--deploy-id", "d1"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)
        d = json.loads(self._cli("dod").stdout)
        self.assertEqual(d["flow"], "build")
        self.assertEqual(d["terminal"], "Released")
        self.assertIs(d["has_verification_evidence"], True)
        self.assertTrue(d["dod_met"])

    # ---- policy declares the flow commands ----
    def test_flow_commands_in_policy(self):
        with open(_POLICY, encoding="utf-8") as f:
            pol = json.load(f)
        by_name = {c["name"]: c for c in pol["commands"]}
        self.assertIn("flow", by_name)
        self.assertIn("flow-finish", by_name)
        self.assertEqual(by_name["flow"]["group"], "flows")
        self.assertEqual(by_name["flow-finish"]["group"], "flows")
        self.assertTrue(by_name["flow"]["body"].strip())          # per-type agent-driving body
        self.assertTrue(by_name["flow-finish"]["body"].strip())


class PanelEnforcementTests(TmpCase):
    """The PANEL-ENFORCEMENT GATE (Approach B). Closes the diagnosed hole: a CLEAN review
    (unresolved_critical_high == 0) could be recorded with the model-diverse seats SILENTLY skipped
    (codex/opencode outcome 'skipped', reason off/never/available_not_run) — so /review + /ship passed
    while no diverse reviewer ever looked. The gate refuses such a clean high-risk review unless the
    seat was RUN (a verdict) or DELIBERATELY acknowledged (skip_ack). It is PURE and best-effort: it
    spawns NOTHING, never fires for a genuinely un-runnable reviewer, and never fires below T3."""
    import argparse as _ap

    def _cli(self, *a):
        return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", self.tmp]
                              + list(a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    @staticmethod
    def _skipped(reason, ack=None):
        from lib.review_seats import _seat
        return _seat("skipped", reason=reason, skip_ack=ack)

    @staticmethod
    def _seat_named(outcome, reason=None):
        from lib.review_seats import _seat
        return _seat(outcome, reason=reason)

    # ---------- pure panel_skip_block() unit locks ----------
    def test_silent_below_T3(self):
        from lib.review_seats import panel_skip_block
        seats = {"codex": self._skipped("off"), "opencode": self._skipped("off")}
        for tier in ("T0", "T1", "T2", None):
            self.assertIsNone(panel_skip_block(tier, seats))   # panel not engaged below T3

    def test_fires_on_off_unacked_T4(self):
        from lib.review_seats import panel_skip_block
        seats = {"codex": self._skipped("off"), "opencode": self._seat_named("used")}
        self.assertEqual(panel_skip_block("T4", seats), ("codex", "off"))

    def test_fires_on_available_not_run_unacked(self):
        from lib.review_seats import panel_skip_block
        seats = {"codex": self._seat_named("used"),
                 "opencode": self._skipped("available_not_run")}
        self.assertEqual(panel_skip_block("T3", seats), ("opencode", "available_not_run"))

    def test_fires_on_never_unacked(self):
        from lib.review_seats import panel_skip_block
        seats = {"codex": self._skipped("never"), "opencode": self._seat_named("used")}
        self.assertEqual(panel_skip_block("T4", seats), ("codex", "never"))

    def test_ack_suppresses_off_and_available(self):
        from lib.review_seats import panel_skip_block
        seats = {"codex": self._skipped("off", ack="diverse review n/a — offline"),
                 "opencode": self._skipped("available_not_run", ack="ran by hand, no findings")}
        self.assertIsNone(panel_skip_block("T4", seats))   # both deliberately acknowledged

    def test_unrunnable_and_neutral_never_fire(self):
        from lib.review_seats import panel_skip_block
        # missing / present_noauth / no_credit / unavailable / seat_error / used / low_risk: NEVER
        for codex_seat in (self._seat_named("unavailable", "missing"),
                           self._seat_named("unavailable", "present_noauth"),
                           self._seat_named("unavailable", "seat_error"),
                           self._seat_named("no_credit", "quota"),
                           self._seat_named("used"),
                           self._skipped("low_risk")):
            seats = {"codex": codex_seat, "opencode": self._seat_named("used")}
            self.assertIsNone(panel_skip_block("T4", seats), codex_seat)

    def test_deterministic_first_offender(self):
        from lib.review_seats import panel_skip_block
        # both silently skipped -> codex (first in order) is reported, not opencode
        seats = {"codex": self._skipped("off"), "opencode": self._skipped("available_not_run")}
        self.assertEqual(panel_skip_block("T4", seats), ("codex", "off"))

    def test_seat_record_carries_skip_ack(self):
        s = self._skipped("off", ack="deliberate")
        self.assertEqual(s["skip_ack"], "deliberate")
        self.assertEqual((s["outcome"], s["reason"]), ("skipped", "off"))

    def test_low_risk_skip_never_carries_ack(self):
        # the low_risk skip path must NOT carry an ack (panel not engaged there)
        import cli
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True)
        args = self._ap.Namespace(codex="auto", skip_codex_ack="should be ignored")
        s = cli._codex_review_seat(zd, args, "T1")
        self.assertEqual(s["reason"], "low_risk")
        self.assertIsNone(s.get("skip_ack"))

    def test_off_seat_carries_ack_via_seat_builder(self):
        import cli
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True)
        args = self._ap.Namespace(codex="off", skip_codex_ack="offline box")
        s = cli._codex_review_seat(zd, args, "T4")
        self.assertEqual((s["outcome"], s["reason"]), ("skipped", "off"))
        self.assertEqual(s["skip_ack"], "offline box")

    def test_getattr_no_arg_does_not_raise(self):
        # partial Namespace (no skip_*_ack, no opencode_*) must not raise — getattr defaults
        import cli
        zd = os.path.join(self.tmp, ".zaude"); os.makedirs(zd, exist_ok=True)
        cs = cli._codex_review_seat(zd, self._ap.Namespace(), "T4")
        os_ = cli._opencode_review_seat(zd, self._ap.Namespace(), "T4")
        self.assertIn(cs["outcome"], ("skipped", "unavailable", "no_credit", "used"))
        self.assertIn(os_["outcome"], ("skipped", "unavailable", "no_credit", "used"))

    def test_panel_skip_block_never_raises_on_bad_shape(self):
        from lib.review_seats import panel_skip_block
        self.assertIsNone(panel_skip_block("T4", None))
        self.assertIsNone(panel_skip_block("T4", {}))
        self.assertIsNone(panel_skip_block("T4", {"codex": None}))
        self.assertIsNone(panel_skip_block("T4", {"codex": {}}))

    # ---------- cmd_review integration locks ----------
    def _to_tested_T4(self):
        """Drive a fresh project to Tested at T4 (the state /review consumes)."""
        self.assertEqual(self._cli("init", "--text", "x", "--mode", "enforce").returncode, 0)
        for cmd in (["clarify", "--acceptance", "a"], ["prioritize", "--decision", "d"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T4"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "t", "--exit", "0"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)

    def _review_inproc(self, ns_kwargs):
        """Run cli.cmd_review in-process with BOTH probes forced READY (no spawn). Returns rc."""
        import cli, lib.codex as cx, lib.opencode as oc
        ready = lambda *a, **k: {"status": "ready", "version": "1", "auth_source": "env",
                                 "detail": "ok", "checked_at": time.time()}
        oc_ready = lambda *a, **k: {"status": oc.READY, "version": "1", "detail": "ok"}
        co, oo = cx.probe, oc.probe
        cx.probe, oc.probe = ready, oc_ready
        try:
            base = dict(path=self.tmp, summary="", unresolved="0",
                        codex="auto", codex_verdict=None, codex_summary="", codex_error=None,
                        codex_retry_at=None, opencode="auto", opencode_verdict=None,
                        opencode_summary="", opencode_error=None, opencode_retry_at=None,
                        skip_codex_ack=None, skip_opencode_ack=None)
            base.update(ns_kwargs)
            return cli.cmd_review(self._ap.Namespace(**base))
        finally:
            cx.probe, oc.probe = co, oo

    def _ledger_path(self):
        return os.path.join(self.tmp, ".zaude", "artifacts", "review-ledger.json")

    def _current_state(self):
        proj = st.reduce(trace.read_trace(os.path.join(self.tmp, ".zaude"), self.root, verify=True))
        return proj["current_state"]

    def test_clean_T4_both_ready_no_ack_refuses_writes_nothing(self):
        # the regression itself: clean review, both probes READY but seats off-by-default? No —
        # 'auto' + READY => available_not_run for BOTH; clean review must REFUSE and write nothing.
        self._to_tested_T4()
        rc = self._review_inproc({"unresolved": "0"})
        self.assertEqual(rc, 3)
        self.assertFalse(os.path.exists(self._ledger_path()))   # NO ledger written
        self.assertEqual(self._current_state(), "Tested")       # state UNCHANGED

    def test_clean_T4_off_no_ack_refuses(self):
        self._to_tested_T4()
        rc = self._review_inproc({"unresolved": "0", "codex": "off", "opencode": "off"})
        self.assertEqual(rc, 3)
        self.assertFalse(os.path.exists(self._ledger_path()))
        self.assertEqual(self._current_state(), "Tested")

    def test_clean_T4_with_acks_records_and_ledger_carries_ack(self):
        self._to_tested_T4()
        rc = self._review_inproc({"unresolved": "0", "codex": "off", "opencode": "off",
                                  "skip_codex_ack": "offline box",
                                  "skip_opencode_ack": "offline box"})
        self.assertEqual(rc, 0)
        led = json.load(open(self._ledger_path(), encoding="utf-8"))
        self.assertEqual(led["review_seats"]["codex"]["skip_ack"], "offline box")
        self.assertEqual(led["review_seats"]["opencode"]["skip_ack"], "offline box")
        self.assertEqual(self._current_state(), "Reviewed")

    def test_clean_T4_with_verdicts_records(self):
        self._to_tested_T4()
        rc = self._review_inproc({"unresolved": "0", "codex_verdict": "pass",
                                  "opencode_verdict": "pass"})
        self.assertEqual(rc, 0)
        led = json.load(open(self._ledger_path(), encoding="utf-8"))
        self.assertEqual(led["review_seats"]["codex"]["outcome"], "used")
        self.assertEqual(led["review_seats"]["opencode"]["outcome"], "used")

    def test_unresolved_gt_zero_bypasses_panel_gate(self):
        # not a clean review -> the panel gate must NOT engage (the ship gate already blocks it).
        self._to_tested_T4()
        rc = self._review_inproc({"unresolved": "2", "codex": "off", "opencode": "off"})
        self.assertEqual(rc, 0)
        led = json.load(open(self._ledger_path(), encoding="utf-8"))
        self.assertEqual(led["unresolved_critical_high"], 2)

    def test_absent_probes_clean_still_records(self):
        # best-effort preserved: when both probes are MISSING (un-runnable), a clean review records.
        self._to_tested_T4()
        import cli, lib.codex as cx, lib.opencode as oc
        miss = lambda *a, **k: {"status": "missing", "version": None, "auth_source": None,
                                "detail": "absent", "checked_at": time.time()}
        oc_miss = lambda *a, **k: {"status": oc.MISSING, "version": None, "detail": "absent"}
        co, oo = cx.probe, oc.probe
        cx.probe, oc.probe = miss, oc_miss
        try:
            rc = cli.cmd_review(self._ap.Namespace(path=self.tmp, summary="", unresolved="0"))
        finally:
            cx.probe, oc.probe = co, oo
        self.assertEqual(rc, 0)
        led = json.load(open(self._ledger_path(), encoding="utf-8"))
        self.assertEqual(led["review_seats"]["codex"]["outcome"], "unavailable")
        self.assertEqual(self._current_state(), "Reviewed")

    def test_probe_that_raises_degrades_and_never_blocks(self):
        # a probe that RAISES degrades the seat to unavailable(seat_error) -> never blocks a clean
        # review (the panel gate only fires on a real available-but-skipped seat).
        self._to_tested_T4()
        import cli, lib.codex as cx, lib.opencode as oc
        def boom(*a, **k):
            raise RuntimeError("probe blew up")
        co, oo = cx.probe, oc.probe
        cx.probe, oc.probe = boom, boom
        try:
            rc = cli.cmd_review(self._ap.Namespace(path=self.tmp, summary="", unresolved="0"))
        finally:
            cx.probe, oc.probe = co, oo
        self.assertEqual(rc, 0)
        led = json.load(open(self._ledger_path(), encoding="utf-8"))
        self.assertEqual(led["review_seats"]["codex"]["outcome"], "unavailable")
        self.assertEqual(led["review_seats"]["codex"]["reason"], "seat_error")
        self.assertEqual(self._current_state(), "Reviewed")


class OnboardGitignoreTests(TmpCase):
    # ZI-001 + codex review HIGH: .zaude sidecars (incl. opencode.json) must be gitignored for
    # fresh AND existing-git projects, idempotently.
    def test_fresh_gitignore_includes_both_health_caches(self):
        from lib import onboard
        onboard.git_init(self.tmp)
        gi = open(os.path.join(self.tmp, ".gitignore"), encoding="utf-8").read()
        self.assertIn(".zaude/codex.json", gi)
        self.assertIn(".zaude/opencode.json", gi)        # the entry the fresh-init list missed
        self.assertIn(".zaude/memory/", gi)

    def test_existing_git_project_still_gets_entries(self):
        from lib import onboard
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)   # simulate an existing repo
        self.assertFalse(onboard.git_init(self.tmp))                 # not a NEW repo
        gi = open(os.path.join(self.tmp, ".gitignore"), encoding="utf-8").read()
        self.assertIn(".zaude/opencode.json", gi)                   # entries added anyway (was the bug)
        self.assertIn(".zaude/codex.json", gi)

    def test_ensure_gitignore_idempotent_and_preserves_existing(self):
        from lib import onboard
        gi = os.path.join(self.tmp, ".gitignore")
        with open(gi, "w", encoding="utf-8") as f:
            f.write("node_modules/\n")                               # a pre-existing user entry
        onboard.ensure_gitignore(self.tmp)
        first = open(gi, encoding="utf-8").read()
        onboard.ensure_gitignore(self.tmp)
        second = open(gi, encoding="utf-8").read()
        self.assertEqual(first, second)                             # no duplicate entries on re-run
        self.assertIn("node_modules/", second)                     # user content preserved
        self.assertIn(".zaude/opencode.json", second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
