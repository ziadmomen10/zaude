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
        # full chain to Reviewed at T4 with opencode absent on this box -> /review still commits (0),
        # the ledger records BOTH seats, and unresolved_critical_high is untouched by either seat.
        for cmd in (["init", "--text", "x", "--mode", "enforce"],
                    ["clarify", "--acceptance", "a"], ["prioritize", "--decision", "d"],
                    ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                    ["classify-risk", "--tier", "T4"], ["approve", "--by", "op"], ["implement"],
                    ["test", "--cmd", "pytest", "--exit", "0"]):
            self.assertEqual(self._cli(*cmd).returncode, 0, cmd)
        r = self._cli("review", "--unresolved", "0")
        self.assertEqual(r.returncode, 0, r.stderr)           # opencode absent NEVER fails /review
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

if __name__ == "__main__":
    unittest.main(verbosity=2)
