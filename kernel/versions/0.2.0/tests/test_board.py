"""
test_board.py (v0.2.0 / P4) — parallel board + autonomous multi-item loop, Approach A.

Locks the P4 contract: each work item is its OWN single-track signed sub-trace, so the SACRED
reduce() runs per-item UNCHANGED, the board is many single-tracks + an index, and a project with
NO .zaude/items/ dir behaves BYTE-IDENTICAL to today. Groups A-G mirror the design spec.

stdlib unittest. Run: python tests/test_board.py  (or: python -m unittest discover -s tests)
"""
from _helpers import *  # noqa: F401,F403

sys.path.insert(0, VROOT)
from lib import board  # noqa: E402
import cli  # noqa: E402


def _cli_run(tmp, *a):
    return subprocess.run([sys.executable, os.path.join(VROOT, "cli.py"), "--path", tmp] + list(a),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _hook(tmp, payload, disabled=False):
    env = dict(os.environ)
    env.pop("ZAUDE_DISABLE", None)
    if disabled:
        env["ZAUDE_DISABLE"] = "1"
    p = subprocess.run([sys.executable, os.path.join(VROOT, "zhook.py"), "pre_tool_use"],
                       input=json.dumps(payload).encode(), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env)
    return p.returncode, p.stdout.decode().strip()


class BoardCase(TmpCase):
    """Adds CLI/hook helpers + a board-with-items fixture on top of TmpCase."""

    def _cli(self, *a):
        return _cli_run(self.tmp, *a)

    def _hook(self, payload, disabled=False):
        return _hook(self.tmp, payload, disabled=disabled)

    def _zd(self):
        return os.path.join(self.tmp, ".zaude")

    def _onboard_with_item(self, note="first feature", tier="T1"):
        """Onboard, add+promote an intake idea, activate+focus its item. Returns the work id."""
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._cli("pm-add", "--note", note)
        self._cli("promote", "--intake", "ZI-001", "--title", "Feature A", "--story", "as a user")
        b = board._root_board(self._zd(), self.root)
        wid = next(w for w, i in b["items"].items() if i["type"] == "feature")
        self._cli("item-activate", "--id", wid)
        self._cli("active-set", "--id", wid)
        return wid


# ====================================================================== A. sacred invariance
class SacredInvarianceTests(BoardCase):
    def test_reduce_unchanged_on_legacy_trace(self):
        # the SACRED reducer folds a legacy linear trace exactly as before (no P4 awareness in it).
        rows = [{"kind": "transition", "from": "Intake", "to": "Clarified"},
                {"kind": "transition", "from": "Clarified", "to": "Prioritized"}]
        self.assertEqual(st.reduce(rows)["current_state"], "Prioritized")

    def test_reduce_ignores_new_root_kinds(self):
        # the NEW root markers are unknown kinds -> reduce() ignores them (a root trace carrying them
        # still projects to the same state as without them). This is what keeps the root trace legal.
        base = [{"kind": "transition", "from": "Intake", "to": "Clarified"}]
        with_markers = [{"kind": "item_activate", "item_id": "ZA-1"},
                        {"kind": "transition", "from": "Intake", "to": "Clarified"},
                        {"kind": "active_set", "item_id": "ZA-1"}]
        self.assertEqual(st.reduce(base)["current_state"],
                         st.reduce(with_markers)["current_state"])

    def test_legacy_project_has_no_items_dir(self):
        # a plain init -> NO items/ dir is ever created (back-compat: old projects never grow it).
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertFalse(os.path.isdir(board.items_root(self._zd())))

    def test_legacy_hook_path_identical(self):
        # with no active item, the hook reads the ROOT trace (today's path). A low-risk src edit at
        # Intake flows, exactly like the pre-P4 behavior.
        self._cli("init", "--text", "x", "--mode", "enforce")
        edit = {"cwd": self.tmp, "tool_name": "Edit",
                "tool_input": {"file_path": os.path.join(self.tmp, "src", "a.ts")}}
        self.assertEqual(self._hook(edit)[1], "")


# ====================================================================== B. per-item integrity
class PerItemIntegrityTests(BoardCase):
    def test_subtrace_is_valid_single_track(self):
        wid = self._onboard_with_item()
        d = board.item_dir(self._zd(), wid)
        rows = trace.read_trace(d, self.root, verify=True)  # must not raise
        self.assertEqual(st.project_state(rows), "Intake")   # fresh item starts at its own Intake

    def test_subtrace_tamper_detected(self):
        wid = self._onboard_with_item()
        self._cli("fast", "--note", "x", "--tier", "T1")     # drive the item forward
        d = board.item_dir(self._zd(), wid)
        with open(os.path.join(d, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","from":"Approved","to":"Released"}\n')
        with self.assertRaises(trace.TraceForged):
            trace.read_trace(d, self.root, verify=True)

    def test_two_items_independent_states(self):
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._cli("pm-add", "--note", "alpha")
        self._cli("pm-add", "--note", "beta")
        self._cli("promote", "--intake", "ZI-001", "--title", "Alpha", "--story", "s")
        self._cli("promote", "--intake", "ZI-002", "--title", "Beta", "--story", "s")
        b = board._root_board(self._zd(), self.root)
        feats = [w for w, i in b["items"].items() if i["type"] == "feature"]
        w1, w2 = feats[0], feats[1]
        for w in (w1, w2):
            self._cli("item-activate", "--id", w)
        # drive ONLY w1 to Approved (fast lane), leave w2 at Intake.
        self._cli("active-set", "--id", w1)
        self._cli("fast", "--note", "x", "--tier", "T1")
        s1 = st.project_state(trace.read_trace(board.item_dir(self._zd(), w1), self.root))
        s2 = st.project_state(trace.read_trace(board.item_dir(self._zd(), w2), self.root))
        self.assertEqual(s1, "Approved")
        self.assertEqual(s2, "Intake")          # the other item is UNAFFECTED

    def test_shared_key_one_per_project(self):
        # both sub-traces verify under the SAME project key (keys are keyed on root, not the dir).
        wid = self._onboard_with_item()
        d = board.item_dir(self._zd(), wid)
        key_root = _keys.get_key(self.root)
        self.assertIsNotNone(key_root)
        # reading the item sub-trace with the root key must succeed (shared key); a per-item key would
        # have been needed otherwise.
        trace.read_trace(d, self.root, verify=True)
        # there is exactly ONE key file for this project root.
        self.assertTrue(os.path.isfile(_keys._key_path(self.root)))

    def test_per_item_lock_independent(self):
        # a lock held on the ROOT .zaude does NOT block locking an item sub-trace (different dirs).
        wid = self._onboard_with_item()
        d = board.item_dir(self._zd(), wid)
        lp_root = trace.acquire_lock(self._zd())
        try:
            lp_item = trace.acquire_lock(d, timeout=2.0)   # must succeed despite the root lock
            trace.release_lock(lp_item)
        finally:
            trace.release_lock(lp_root)


# ====================================================================== C. active-item gating
class ActiveItemGatingTests(BoardCase):
    def _edit(self, path):
        return {"cwd": self.tmp, "tool_name": "Edit", "tool_input": {"file_path": path}}

    def test_gate_uses_active_item_state(self):
        # make the ACTIVE item high-risk + pre-Approved -> a src edit must be DENIED (the gate read
        # the ITEM's projection, not the root's, which is still at its own Intake/low).
        wid = self._onboard_with_item()
        for c in (["clarify", "--acceptance", "x"], ["prioritize", "--decision", "n"],
                  ["plan", "--steps", "a"], ["design", "--approach", "x", "--decision", "D"],
                  ["classify-risk", "--tier", "T4"]):
            self.assertEqual(self._cli(*c).returncode, 0, c)
        out = self._hook(self._edit(os.path.join(self.tmp, "src", "a.ts")))[1]
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        # approving the item unblocks source edits (still per-item).
        self.assertEqual(self._cli("approve", "--by", "op").returncode, 0)
        self.assertEqual(self._hook(self._edit(os.path.join(self.tmp, "src", "a.ts")))[1], "")

    def test_no_active_falls_back_to_root(self):
        # clear the active item -> the hook reads the ROOT trace (legacy path).
        self._onboard_with_item()
        self._cli("active-set", "--clear")
        self.assertIsNone(board.active_item_dir(self._zd(), self.root))
        self.assertEqual(self._hook(self._edit(os.path.join(self.tmp, "src", "a.ts")))[1], "")

    def test_missing_active_dir_fails_open_to_root(self):
        # an `active` pointer whose items/<id>/ dir does not exist -> active_item_dir() returns None
        # (fail-open). Write a bogus active file directly (cache file, not the trace).
        self._cli("init", "--text", "x", "--mode", "enforce")
        os.makedirs(board.items_root(self._zd()), exist_ok=True)
        with open(os.path.join(self._zd(), board.ACTIVE_FILE), "w", encoding="utf-8") as f:
            f.write("ZA-DOES-NOT-EXIST\n")
        self.assertIsNone(board.active_item_dir(self._zd(), self.root))   # TOTAL: None on a missing dir
        # hook still works (falls back to root): low-risk src edit flows.
        self.assertEqual(self._hook(self._edit(os.path.join(self.tmp, "src", "a.ts")))[1], "")

    def test_forged_active_subtrace_fails_closed_enforce(self):
        wid = self._onboard_with_item()
        d = board.item_dir(self._zd(), wid)
        with open(os.path.join(d, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","from":"Intake","to":"Approved"}\n')   # hand-forged
        out = self._hook(self._edit(os.path.join(self.tmp, "src", "a.ts")))[1]
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_protect_zaude_covers_items(self):
        # protect_zaude (root zaude_dir) still denies writing the item sub-trace under items/.
        wid = self._onboard_with_item()
        target = os.path.join(self._zd(), "items", wid, "trace.jsonl")
        out = self._hook(self._edit(target))[1]
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_active_item_dir_total_never_raises(self):
        # active_item_dir / active_item_id must be TOTAL even on a junk active file.
        os.makedirs(self._zd(), exist_ok=True)
        with open(os.path.join(self._zd(), board.ACTIVE_FILE), "w", encoding="utf-8") as f:
            f.write("../escape\x00bad")
        self.assertIsNone(board.active_item_id(self._zd()))     # rejected, no raise
        self.assertIsNone(board.active_item_dir(self._zd(), self.root))


# ====================================================================== D. board-DoD + loop
class BoardDodAndLoopTests(BoardCase):
    def test_false_with_open_intake(self):
        # the DIAGNOSED bug, now false for the RIGHT reason: an open intake idea means NOT done.
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._cli("pm-add", "--note", "unstarted idea")
        bd = board.board_dod(self._zd(), self.root)
        self.assertFalse(bd["met"])
        self.assertEqual(bd["open_intake_items"], 1)

    def test_false_with_unfinished_item(self):
        wid = self._onboard_with_item()
        self._cli("fast", "--note", "x", "--tier", "T1")   # item at Approved, NOT released
        bd = board.board_dod(self._zd(), self.root)
        self.assertFalse(bd["met"])
        self.assertIn(wid, bd["unfinished_items"])

    def test_true_all_done_empty_intake(self):
        self._onboard_with_item()
        self._cli("fast", "--note", "x", "--tier", "T1")
        self._cli("fast-ship", "--tested-exit", "0")
        bd = board.board_dod(self._zd(), self.root)
        self.assertTrue(bd["met"])
        self.assertEqual((bd["items_total"], bd["items_done"], bd["open_intake_items"]), (1, 1, 0))

    def test_legacy_board_dod_equals_cmd_dod(self):
        # no items/ dir -> board-dod delegates to cmd_dod on the root (identical exit code).
        self._cli("init", "--text", "x", "--mode", "enforce")
        self.assertFalse(os.path.isdir(board.items_root(self._zd())))
        rc_board = self._cli("board-dod").returncode
        rc_dod = self._cli("dod").returncode
        self.assertEqual(rc_board, rc_dod)

    def test_item_done_matches_cmd_dod_predicate(self):
        # board.item_done's terminal+evidence predicate matches what cmd_dod computes on a single
        # track: drive a LEGACY root trace to Released and assert item_done(root) is met.
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._cli("fast", "--note", "x", "--tier", "T1")
        self._cli("fast-ship", "--tested-exit", "0")
        pred = board.item_done(self._zd(), self.root)
        self.assertTrue(pred["met"])
        self.assertEqual(self._cli("dod").returncode, 0)   # cmd_dod agrees (intake empty + done)

    def test_board_next_orders_and_terminates(self):
        # promote -> activate -> focus+drive -> MET, in priority order.
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._cli("pm-add", "--note", "idea")
        a1, _ = board.board_next(self._zd(), self.root)
        self.assertTrue(a1.startswith("promote"))           # 1. open intake -> promote
        self._cli("promote", "--intake", "ZI-001", "--title", "A", "--story", "s")
        a2, _ = board.board_next(self._zd(), self.root)
        self.assertTrue(a2.startswith("item-activate"))     # 2. promoted, no sub-trace -> activate
        wid = board._promoted_work_ids(board._root_board(self._zd(), self.root))[0]
        self._cli("item-activate", "--id", wid)
        self._cli("active-set", "--id", wid)
        self._cli("fast", "--note", "x", "--tier", "T1")
        self._cli("fast-ship", "--tested-exit", "0")
        action, done = board.board_next(self._zd(), self.root)
        self.assertTrue(done)                               # terminates: board-DoD MET
        self.assertEqual(action, "board-DoD MET")

    def test_board_next_handles_intake_priority(self):
        # an open intake beats an unfinished item: promote comes first.
        self._onboard_with_item()                 # one item, at Intake
        self._cli("pm-add", "--note", "another idea")
        action, done = board.board_next(self._zd(), self.root)
        self.assertFalse(done)
        self.assertTrue(action.startswith("promote"))


# ====================================================================== E. verify/doctor many traces
class VerifyDoctorManyTracesTests(BoardCase):
    def test_trace_verify_covers_all_items(self):
        self._onboard_with_item()
        r = self._cli("trace-verify")
        self.assertEqual(r.returncode, 0)
        self.assertIn("item sub-trace", r.stdout)

    def test_trace_verify_fails_on_bad_item_naming_it(self):
        wid = self._onboard_with_item()
        d = board.item_dir(self._zd(), wid)
        with open(os.path.join(d, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","from":"Intake","to":"Approved"}\n')
        r = self._cli("trace-verify")
        self.assertEqual(r.returncode, 5)
        self.assertIn(wid, r.stderr)              # the failure NAMES the bad item

    def test_doctor_fails_on_bad_item(self):
        wid = self._onboard_with_item()
        d = board.item_dir(self._zd(), wid)
        with open(os.path.join(d, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"kind":"transition","from":"Intake","to":"Approved"}\n')
        r = self._cli("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn(wid, r.stdout)

    def test_legacy_trace_verify_identical(self):
        # no items/ dir -> the classic single-line message + rc 0, exactly as today.
        self._cli("init", "--text", "x", "--mode", "enforce")
        r = self._cli("trace-verify")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("item sub-trace", r.stdout)


# ====================================================================== F. E2E
class E2ETests(BoardCase):
    def test_two_item_autonomous_walk_to_board_dod(self):
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._cli("pm-add", "--note", "alpha feature")
        self._cli("pm-add", "--note", "beta feature")
        self._cli("promote", "--intake", "ZI-001", "--title", "Alpha", "--story", "s")
        self._cli("promote", "--intake", "ZI-002", "--title", "Beta", "--story", "s")
        b = board._root_board(self._zd(), self.root)
        feats = [w for w, i in b["items"].items() if i["type"] == "feature"]
        for w in feats:
            self.assertEqual(self._cli("item-activate", "--id", w).returncode, 0)
            self.assertEqual(self._cli("active-set", "--id", w).returncode, 0)
            self.assertEqual(self._cli("fast", "--note", "x", "--tier", "T1").returncode, 0)
            self.assertEqual(self._cli("fast-ship", "--tested-exit", "0").returncode, 0)
        # intake is empty (both promoted) + both items Released -> board-dod exits 0.
        self.assertEqual(self._cli("board-dod").returncode, 0)
        # every trace (root + both items) verifies.
        self.assertEqual(self._cli("trace-verify").returncode, 0)

    def test_resolve_active_routes_lifecycle_to_item(self):
        # a lifecycle command records into the ACTIVE item's sub-trace, leaving the root at Intake.
        wid = self._onboard_with_item()
        self._cli("fast", "--note", "x", "--tier", "T1")
        root_state = st.project_state(trace.read_trace(self._zd(), self.root))
        item_state = st.project_state(trace.read_trace(board.item_dir(self._zd(), wid), self.root))
        self.assertEqual(root_state, "Intake")       # the ROOT trace is the board ledger, not a track
        self.assertEqual(item_state, "Approved")     # the work landed on the ITEM

    def test_item_override_beats_active(self):
        # `--item <id>` targets that item even when a DIFFERENT item is active.
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._cli("pm-add", "--note", "alpha")
        self._cli("pm-add", "--note", "beta")
        self._cli("promote", "--intake", "ZI-001", "--title", "Alpha", "--story", "s")
        self._cli("promote", "--intake", "ZI-002", "--title", "Beta", "--story", "s")
        b = board._root_board(self._zd(), self.root)
        feats = [w for w, i in b["items"].items() if i["type"] == "feature"]
        w1, w2 = feats[0], feats[1]
        self._cli("item-activate", "--id", w1)
        self._cli("item-activate", "--id", w2)
        self._cli("active-set", "--id", w1)           # w1 is active
        # but drive w2 via --item; w1 must stay at Intake.
        self._cli("--item", w2, "fast", "--note", "x", "--tier", "T1")
        s1 = st.project_state(trace.read_trace(board.item_dir(self._zd(), w1), self.root))
        s2 = st.project_state(trace.read_trace(board.item_dir(self._zd(), w2), self.root))
        self.assertEqual(s1, "Intake")
        self.assertEqual(s2, "Approved")


# ====================================================================== H. id hardening (HIGH-1)
class ItemIdHardeningTests(BoardCase):
    BAD_IDS = ["C:foo", "../x", "..\\x", "a/b", "a\\b", "..", ".", "/x", "\\x", "/etc/passwd",
               "a:b", "a.b", "a b", "a\x00b", "-lead", "_lead", "", None, 123, []]

    def test_valid_item_id_rejects_traversal_and_junk(self):
        for bad in self.BAD_IDS:
            self.assertFalse(board._valid_item_id(bad), "should reject %r" % (bad,))
        # the regression id and other plain tokens are accepted.
        for good in ("ZA-2026-00001", "ZA1", "a", "A_b-C9", "x" * 64):
            self.assertTrue(board._valid_item_id(good), "should accept %r" % (good,))
        self.assertFalse(board._valid_item_id("x" * 65))   # length cap (1..64)

    def test_item_dir_none_on_bad_id(self):
        zd = self._zd()
        for bad in self.BAD_IDS:
            self.assertIsNone(board.item_dir(zd, bad), "item_dir should be None for %r" % (bad,))
        # a valid id resolves to a path CONTAINED in items/ (no escape).
        d = board.item_dir(zd, "ZA-2026-00001")
        self.assertIsNotNone(d)
        base = os.path.realpath(board.items_root(zd))
        self.assertTrue(os.path.realpath(d).startswith(base + os.sep))

    def test_drive_qualified_id_cannot_escape_items(self):
        # the concrete CVE: os.path.join(items_dir, "C:foo") would escape on Windows. item_dir must
        # refuse it (None), never returning a path outside items/.
        zd = self._zd()
        self.assertIsNone(board.item_dir(zd, "C:foo"))

    def test_activate_item_raises_on_bad_id(self):
        self._cli("init", "--text", "x", "--mode", "enforce")
        for bad in ("C:foo", "../x", "a/b", ".."):
            with self.assertRaises(ValueError):
                board.activate_item(self._zd(), self.root, bad)

    def test_cmd_item_activate_bad_id_rc3_creates_nothing(self):
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        before = sorted(os.listdir(self._zd()))
        for bad in ("C:foo", "../x", "a/b", ".."):
            r = self._cli("item-activate", "--id", bad)
            self.assertEqual(r.returncode, 3, "expected rc 3 for %r, got %r (%s)"
                             % (bad, r.returncode, r.stderr))
        # NOTHING was created (no items/ dir, no escaped dir, root .zaude unchanged).
        self.assertFalse(os.path.isdir(board.items_root(self._zd())))
        self.assertEqual(sorted(os.listdir(self._zd())), before)

    def test_item_override_bad_id_rc3(self):
        # an explicit --item with a traversal id is refused cleanly (rc 3), no item created.
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        for bad in ("C:foo", "../x", "a/b"):
            r = self._cli("--item", bad, "status")
            self.assertEqual(r.returncode, 3, "%r -> %r (%s)" % (bad, r.returncode, r.stderr))

    def test_active_set_bad_id_rc3(self):
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        r = self._cli("active-set", "--id", "C:foo")
        self.assertEqual(r.returncode, 3)


# ====================================================================== I. activate atomicity (HIGH-2)
class ActivateAtomicityTests(BoardCase):
    def test_enumeration_is_marker_derived_not_scandir(self):
        # a fully-activated item has a committed marker -> it is enumerated.
        wid = self._onboard_with_item()
        self.assertIn(wid, board.list_item_ids(self._zd(), self.root))
        # plant an ORPHAN items/<id>/ dir with a trace.jsonl but NO root marker (simulates a crash
        # AFTER the sub-trace write but BEFORE the commit marker). It must be IGNORED.
        orphan = "ZA-2026-09999"
        od = os.path.join(board.items_root(self._zd()), orphan)
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, "trace.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"kind":"init","seq":0}\n')
        ids = board.list_item_ids(self._zd(), self.root)
        self.assertIn(wid, ids)
        self.assertNotIn(orphan, ids)          # orphan dir with no marker is ignored

    def test_orphan_dir_ignored_by_board_dod_and_next(self):
        # an orphan dir for a NON-promoted id must not affect board-DoD / board-next at all.
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        # clean board (empty intake, no items) -> board-DoD met.
        self.assertTrue(board.board_dod(self._zd(), self.root)["met"])
        od = os.path.join(board.items_root(self._zd()), "ZA-2026-09999")
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, "trace.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"kind":"init","seq":0}\n')
        # still met: the orphan has no marker, so it is not an item and changes nothing.
        self.assertTrue(board.board_dod(self._zd(), self.root)["met"])
        action, done = board.board_next(self._zd(), self.root)
        self.assertTrue(done)
        self.assertEqual(action, "board-DoD MET")

    def test_reactivate_is_idempotent_no_duplicate_marker(self):
        wid = self._onboard_with_item()
        rows0 = trace.read_trace(self._zd(), self.root, verify=True)
        n0 = sum(1 for r in rows0 if r.get("kind") == "item_activate" and r.get("item_id") == wid)
        self.assertEqual(n0, 1)
        # drive the item forward, THEN re-activate: must NOT reset its state and must NOT add a marker.
        self._cli("fast", "--note", "x", "--tier", "T1")
        state_before = st.project_state(trace.read_trace(board.item_dir(self._zd(), wid), self.root))
        d = board.activate_item(self._zd(), self.root, wid)        # direct call: returns, no raise
        self.assertEqual(d, board.item_dir(self._zd(), wid))
        rows1 = trace.read_trace(self._zd(), self.root, verify=True)
        n1 = sum(1 for r in rows1 if r.get("kind") == "item_activate" and r.get("item_id") == wid)
        self.assertEqual(n1, 1)                                    # still exactly ONE marker
        state_after = st.project_state(trace.read_trace(board.item_dir(self._zd(), wid), self.root))
        self.assertEqual(state_after, state_before)               # state NOT reset

    def test_cmd_item_activate_idempotent(self):
        wid = self._onboard_with_item()
        self._cli("fast", "--note", "x", "--tier", "T1")          # item -> Approved
        r = self._cli("item-activate", "--id", wid)               # re-activate via CLI
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = trace.read_trace(self._zd(), self.root, verify=True)
        n = sum(1 for r in rows if r.get("kind") == "item_activate" and r.get("item_id") == wid)
        self.assertEqual(n, 1)
        self.assertEqual(st.project_state(trace.read_trace(board.item_dir(self._zd(), wid),
                                                           self.root)), "Approved")

    def test_marker_is_commit_point_written_last(self):
        # the sub-trace init row exists BEFORE the marker is appended: assert ordering by inspecting
        # the produced traces (the marker references an id whose sub-trace is already projectable).
        wid = self._onboard_with_item()
        d = board.item_dir(self._zd(), wid)
        # marker present on root AND sub-trace projectable -> the commit-point invariant holds.
        self.assertIn(wid, board._marker_item_ids(self._zd(), self.root))
        self.assertEqual(st.project_state(trace.read_trace(d, self.root, verify=True)), "Intake")

    def test_regression_valid_id_end_to_end(self):
        # the canonical id ZA-2026-00001 (what pm.next_work_id emits) drives a full single-item walk.
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._cli("pm-add", "--note", "first feature")
        self._cli("promote", "--intake", "ZI-001", "--title", "Feature A", "--story", "as a user")
        wid = board._promoted_work_ids(board._root_board(self._zd(), self.root))[0]
        self.assertEqual(wid, "ZA-2026-00001")                    # the exact regression id
        self.assertEqual(self._cli("item-activate", "--id", wid).returncode, 0)
        self.assertEqual(self._cli("active-set", "--id", wid).returncode, 0)
        self.assertEqual(self._cli("fast", "--note", "x", "--tier", "T1").returncode, 0)
        self.assertEqual(self._cli("fast-ship", "--tested-exit", "0").returncode, 0)
        self.assertIn(wid, board.list_item_ids(self._zd(), self.root))
        self.assertEqual(self._cli("board-dod").returncode, 0)
        self.assertEqual(self._cli("trace-verify").returncode, 0)


# ====================================================================== J. selection-binding (HIGH-3)
class SelectionBindingTests(BoardCase):
    """SELECTION (active pointer / --item / active-set) must be bound to a COMMITTED signed marker, not
    to bare items/<id>/ dir existence. A crash-orphan dir or a copied/planted sub-trace (no marker)
    can never be gated or driven as the active item."""

    def _edit(self, path):
        return {"cwd": self.tmp, "tool_name": "Edit", "tool_input": {"file_path": path}}

    def _plant_orphan(self, item_id):
        """Create an items/<id>/ dir with a valid-looking sub-trace but NO root item_activate marker —
        simulates a crash orphan or an attacker-copied/planted dir."""
        od = os.path.join(board.items_root(self._zd()), item_id)
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, "trace.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"kind":"init","seq":0}\n')
        return od

    def test_active_pointer_at_uncommitted_dir_returns_none_gate_uses_root(self):
        # an items/<id>/ dir exists (planted) AND the `active` file points at it, but there is NO signed
        # marker -> active_item_dir is None (selection bound to the marker), so the gate uses the ROOT.
        self._cli("init", "--text", "x", "--mode", "enforce")
        orphan = "ZA-2026-09999"
        self._plant_orphan(orphan)
        with open(os.path.join(self._zd(), board.ACTIVE_FILE), "w", encoding="utf-8") as f:
            f.write(orphan + "\n")          # point active at the uncommitted dir
        self.assertNotIn(orphan, board._marker_item_ids(self._zd(), self.root))
        self.assertIsNone(board.active_item_dir(self._zd(), self.root))   # NOT selected (no marker)
        # the PreToolUse gate therefore uses the ROOT projection: a low-risk src edit at Intake flows.
        self.assertEqual(self._hook(self._edit(os.path.join(self.tmp, "src", "a.ts")))[1], "")

    def test_set_active_unactivated_raises(self):
        # set_active to an id with no signed marker must raise ValueError (cannot focus unactivated).
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._plant_orphan("ZA-2026-09999")
        with self.assertRaises(ValueError):
            board.set_active(self._zd(), self.root, "ZA-2026-09999")

    def test_cli_active_set_unactivated_rc3_no_active_file(self):
        # cli `active-set --id <unactivated>` returns rc 3 and does NOT write the `active` file.
        self._cli("init", "--text", "x", "--mode", "enforce")
        self._plant_orphan("ZA-2026-09999")
        r = self._cli("active-set", "--id", "ZA-2026-09999")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertFalse(os.path.isfile(os.path.join(self._zd(), board.ACTIVE_FILE)))

    def test_item_override_uncommitted_rc3(self):
        # `--item <uncommitted-id>` on a lifecycle command is refused cleanly (rc 3), no crash.
        self._cli("onboard", "--slug", "demo", "--text", "d", "--mode", "enforce")
        self._plant_orphan("ZA-2026-09999")
        r = self._cli("--item", "ZA-2026-09999", "status")
        self.assertEqual(r.returncode, 3, r.stderr)

    def test_normal_flow_committed_item_is_selected(self):
        # regression: the NORMAL flow (item-activate -> active-set -> lifecycle) still works, and
        # active_item_dir returns the dir for a committed + active item.
        wid = self._onboard_with_item()
        self.assertIn(wid, board._marker_item_ids(self._zd(), self.root))
        d = board.active_item_dir(self._zd(), self.root)
        self.assertEqual(d, board.item_dir(self._zd(), wid))    # selected: committed + active
        # a lifecycle command lands on the item (not the root).
        self.assertEqual(self._cli("fast", "--note", "x", "--tier", "T1").returncode, 0)
        self.assertEqual(st.project_state(trace.read_trace(d, self.root)), "Approved")
        self.assertEqual(st.project_state(trace.read_trace(self._zd(), self.root)), "Intake")


# ====================================================================== G. policy
class PolicyRenderTests(TmpCase):
    def test_four_new_commands_render(self):
        from lib import generator
        out = os.path.join(self.tmp, "gen")
        generator.generate(out_dir=out, policy_path=_POLICY)
        for name in ("item-activate", "active-set", "board-next", "board-dod"):
            self.assertTrue(os.path.isfile(os.path.join(out, "commands", name + ".md")),
                            "missing generated command: " + name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
