"""
vault.py (v0.2.0) — VAULT PROJECTION [vault upgrade, Claude+codex, 2026-06-18].

The kernel scaffolds vault/<slug>/ at onboard, but the lifecycle only ever writes the SIGNED
TRACE — so current-state.md / decisions.md sit as dead stubs after onboarding. This projects the
trace into the human-readable vault so `/start` has a live surface and the operator's decision log
stays current, WITHOUT the vault becoming a second source of truth:

  - current-state.md is REGENERATED each sync (a snapshot of the trace projection, stamped with a
    trace ANCHOR — the chain-tip hash — so you can tell which trace point it reflects). EVERY field
    is derived from the signed, integrity-verified trace (incl. the in-flight intake text, which
    the init row now carries) — nothing comes from an unsigned artifact. [codex review HIGH]
  - decisions.md is APPEND-ONLY + IDEMPOTENT: each decision-bearing trace row becomes one anchored
    line `[ZD-<seq>]`. This is a lightweight **ADR** (Architecture Decision Record, Nygard) log —
    one immutable, dated, anchored entry per decision. A row whose anchor is already present is
    never re-appended, so the operator rule "decisions.md is append-only; never edit existing
    entries" holds across re-syncs.

Hardening (codex review): anchors are matched ONLY in canonical line position and user text is
sanitized so it can never mint a fake `[ZD-..]`/heading/HTML-comment/anchor (anchor-poisoning that
would suppress a future real decision); the current-state write is a UNIQUE-temp + fsync +
os.replace; sync() returns a STRUCTURED status (it never raises into the caller, but it reports
failures honestly so the CLI can exit non-zero). The trace lock is held by the caller so the
read-anchors + append on decisions.md is race-free.

Leaf lib (stdlib only; own writes). A projection failure must never abort or corrupt the
trace-mutating command that triggered it.
"""
import os
import re
import time
import tempfile

# match an anchor ONLY in canonical line position (start of a dated entry), never anywhere a user
# string could have placed the literal "[ZD-n]" — defeats anchor poisoning. [codex review HIGH]
_LINE_ANCHOR_RE = re.compile(r"^- \d{4}-\d\d-\d\d \[ZD-(\d+)\] ", re.M)
# control chars + the Unicode line/paragraph separators that markdown/terminals treat as newlines
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f  ]")
_MAX_RECENT = 8


def _date(ts):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(ts))
    except Exception:
        return "????-??-??"


def _oneline(s, maxlen=240):
    """Collapse arbitrary (operator-supplied) text to ONE safe markdown line: strip all control /
    line-separator chars, and neutralize tokens that could mint a fake anchor, heading, HTML
    comment, or trace-anchor. [codex review HIGH/MEDIUM]"""
    s = _CTRL_RE.sub(" ", str(s if s is not None else ""))
    s = s.replace("[", "(").replace("]", ")")          # cannot mint a [ZD-..] anchor
    s = s.replace("<!--", "< !--").replace("-->", "-- >")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen]


def _decisions_from_rows(rows):
    """Decision-BEARING rows -> [(seq, ts, type, detail)] in trace order. These represent a CHOICE
    (not a mechanical transition): explicit decisions (prioritize/design), the risk tier, waivers,
    and release tokens. `seq` is the row's permanent, integrity-verified trace index — the stable
    anchor."""
    out = []
    for r in rows:
        seq = r.get("seq")
        if not isinstance(seq, int):
            continue
        kind = r.get("kind")
        ts = r.get("ts", 0)
        if kind == "decision":
            what = r.get("what") or "decision"
            did = r.get("decision_id")
            detail = _oneline(r.get("text")) + ((" (decision_id: %s)" % _oneline(did, 40)) if did else "")
            out.append((seq, ts, what, detail or "(no detail)"))
        elif kind == "risk":
            out.append((seq, ts, "risk", "tier=%s" % _oneline(r.get("tier"), 8)))
        elif kind == "waiver":
            out.append((seq, ts, "waiver", "gate=%s bypassed%s"
                        % (_oneline(r.get("gate"), 60), " (scoped/expiring)" if r.get("expires_at") else "")))
        elif kind == "release_token":
            out.append((seq, ts, "release", "deploy token issued"))
    return out


def _recent_events(rows):
    evs = [r for r in rows if r.get("kind") == "transition"][-_MAX_RECENT:]
    return ["%s -> %s via %s" % (_oneline(r.get("from"), 24), _oneline(r.get("to"), 24),
                                 _oneline(r.get("command"), 24) or "?") for r in evs]


def _inflight(rows):
    """The current in-flight intake text, derived from the LAST `init` row in the SIGNED trace
    (the init row carries intake_text) — not from an unsigned artifact. [codex review HIGH]"""
    text = ""
    for r in rows:
        if r.get("kind") == "init" and isinstance(r.get("intake_text"), str):
            text = r["intake_text"]
    return _oneline(text, 400)


def render_current_state(slug, proj, next_cmd, rows, anchor, now):
    """Build the REGENERATED current-state.md body (a snapshot — not append-only). Every field is
    trace-derived."""
    waivers = sorted(proj.get("waived_gates") or [])
    try:
        gen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    except Exception:
        gen = "????"
    inflight = _inflight(rows)
    lines = [
        "# Current state — %s" % _oneline(slug, 80),
        "",
        "_Regenerated from the signed trace by `zaude vault-sync`. Do not hand-edit — changes are "
        "overwritten on the next sync; the trace is the source of truth._",
        "",
        "**Lifecycle state:** %s" % _oneline(proj.get("current_state"), 24),
        "**Risk tier:** %s" % (_oneline(proj.get("risk_tier"), 8) or "unclassified"),
        "**Release token:** %s" % ("active" if proj.get("release_token_active") else "none"),
        "**Live waivers:** %s" % (", ".join(_oneline(w, 40) for w in waivers) if waivers else "none"),
        "**Next:** %s" % (("`%s`" % _oneline(next_cmd, 24)) if next_cmd else "— (terminal / fast-lane)"),
        "",
        "## In flight",
        (inflight or "_No work in flight._"),
        "",
        "## Recent trace events",
    ]
    recent = _recent_events(rows)
    lines += (["- " + e for e in reversed(recent)] if recent else ["_none yet_"])
    lines += ["", "<!-- zaude-trace-anchor head=%s rows=%d generated=%s -->"
              % (_oneline(anchor, 64), len(rows), gen), ""]
    return "\n".join(lines)


def _existing_anchors(path):
    """Set of [ZD-<seq>] anchors already present as CANONICAL dated entries (line-anchored, so
    operator text containing '[ZD-n]' can never mark a real decision as already projected)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(int(m) for m in _LINE_ANCHOR_RE.findall(f.read()))
    except Exception:
        return set()


def append_decisions(path, rows, now):
    """APPEND-ONLY + IDEMPOTENT: add one canonical anchored line per decision-bearing row whose
    [ZD-<seq>] anchor is not already present. Never truncates (only opens in append mode). Returns
    (count_appended, error_or_None). Caller holds the project lock, so read-anchors + append is
    race-free. Never raises."""
    try:
        new = [d for d in _decisions_from_rows(rows) if d[0] not in _existing_anchors(path)]
        if not new:
            return 0, None
        need_header = (not os.path.exists(path)) or os.path.getsize(path) == 0
        with open(path, "a", encoding="utf-8") as f:   # APPEND ONLY — never "w" (no truncation)
            if need_header:
                f.write("# Decisions (append-only)\n\n_Lightweight ADR log — one immutable, "
                        "trace-anchored entry per decision._\n")
            for seq, ts, typ, detail in new:
                f.write("- %s [ZD-%d] %s: %s\n" % (_date(ts or now), seq, _oneline(typ, 24), detail))
        return len(new), None
    except Exception as e:
        return 0, str(e)[:200]


def sync(vault_dir, slug, rows, proj, next_cmd, anchor, now=None):
    """Project the trace into vault/<slug>: regenerate current-state.md (UNIQUE-temp + fsync +
    os.replace) and append-only decisions.md. Returns a STRUCTURED status
    {current_state_written, decisions_appended, errors:[...]} — never raises; the CLI reports it
    honestly and exits non-zero on failure. Caller must hold the project lock."""
    now = now if now is not None else time.time()
    errors = []
    cs_written = False
    cs = os.path.join(vault_dir, "current-state.md")
    body = render_current_state(slug, proj, next_cmd, rows, anchor, now)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=vault_dir, prefix="current-state.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, cs)
        cs_written = True
        tmp = None
    except Exception as e:
        errors.append("current-state write failed: %s" % (str(e)[:200]))
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    n, derr = append_decisions(os.path.join(vault_dir, "decisions.md"), rows, now)
    if derr:
        errors.append("decisions append failed: %s" % derr)
    return {"current_state_written": cs_written, "decisions_appended": n, "errors": errors}
