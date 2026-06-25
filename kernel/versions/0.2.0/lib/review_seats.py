"""
review_seats.py (v0.2.0) — the best-effort external review-panel SEATS (codex + opencode).

Extracted from cli.py (architecture-review finding E: de-god the 1.6k-line dispatcher). Pure seat
logic — it builds the honest, NON-BLOCKING ledger record for each external reviewer and NEVER
changes an exit code or raises into the cycle (the ship gate reads only `unresolved_critical_high`).
cli.py re-exports these names, so `cli._codex_review_seat` / `cli._opencode_review_seat` stay
stable. stdlib + lib leaves only; no cli/trace/state import -> no cycle.
"""
import sys
import time

from lib import gates, codex, opencode, kimi, glm

def _seat(outcome, verdict=None, summary=None, reason=None, retry_at=None, now=None, **extra):
    """A codex review-seat record. `enforced` means ONLY 'codex actually participated' (outcome ==
    used) — never claimed for absence/skip/no-credit (codex-review-MEDIUM). All keys present so the
    ledger schema is stable."""
    s = {"outcome": outcome, "verdict": verdict, "summary": summary, "reason": reason,
         "retry_at": retry_at, "checked_at": now or time.time(), "enforced": (outcome == "used")}
    s.update(extra)
    return s


def _panel_seat(zd, tier, mod, label, mode, verdict, summary, err, retry_arg, fix_hint="",
                skip_ack=None):
    """Build the honest, NON-BLOCKING seat for ONE best-effort external reviewer (codex OR opencode)
    in the review ledger. `mod` is that reviewer's leaf lib. NEVER refuses, NEVER changes the exit
    code, NEVER raises into the cycle — both reviewers are best-effort and the ship gate reads ONLY
    `unresolved_critical_high`, so a seat NEVER sets the gate by itself. The whole body is guarded so
    an unexpected raise degrades to a benign 'unavailable' record. [L13/graceful external reviewers]

    `skip_ack` (an operator-supplied reason string) is carried on the AVAILABLE-but-skipped records
    (off / never / available_not_run). It's what `panel_skip_block` reads to tell a DELIBERATE,
    acknowledged skip apart from a SILENT one when refusing to record a clean high-risk review. The
    `low_risk` skip never carries an ack (the panel isn't engaged there)."""
    now = time.time()
    try:
        mode = (mode or "auto")
        summary = (summary or "")[:500]

        # 1. Explicit operator skip wins over everything else (incl. a stray verdict) — honest:
        #    the operator turned this reviewer off for THIS review. (off must win.) Carries the
        #    skip_ack so an ACKNOWLEDGED off/never skip can pass the clean-high-risk panel gate.
        if mode in ("off", "never"):
            sys.stderr.write("%s: skipped by flag for this review; continuing.\n" % label)
            return _seat("skipped", reason=mode, now=now, skip_ack=skip_ack)

        # 2. Below T3 the external panel isn't engaged (light by default). NO ack — never gates.
        if tier not in gates.HIGH_RISK:
            return _seat("skipped", reason="low_risk", now=now)

        # 3. Driver ran it and got a verdict -> honest 'used'. Clearly back -> clear any backoff.
        if verdict:
            mod.clear_retry(zd)
            return _seat("used", verdict=verdict, summary=summary, now=now)

        # 4. Driver ran it but it FAILED (quota / rate-limit / auth) and reported the error -> record
        #    honestly AND arm the no-credit backoff so it AUTO-RESUMES when the reset window passes.
        if err:
            cls = mod.classify_error(1, err, now=now)
            ra = mod.parse_retry_at(retry_arg) if retry_arg else None
            if ra is None:
                ra = cls.get("retry_at")
            if cls["reason"] in (mod.QUOTA, mod.RATE_LIMIT):
                mod.note_no_credit(zd, cls["reason"], ra)
                sys.stderr.write("%s: %s — continuing without it; will auto-resume%s.\n"
                                 % (label, cls["reason"], " at the retry window" if ra else
                                    " on the next review"))
                return _seat("no_credit", reason=cls["reason"], retry_at=ra, now=now)
            sys.stderr.write("%s: error (%s) — continuing without it.\n" % (label, cls["reason"]))
            return _seat("unavailable", reason=cls["reason"], now=now)

        # 5. No verdict/err: honor a live no-credit backoff (auto-resumes once retry_at passes).
        status = mod.read_status(zd)
        if not mod.due_now(status, now):
            r = status.get("retry") or {}
            sys.stderr.write("%s: in a no-credit/rate-limit backoff — continuing without it "
                             "(auto-resumes at the retry window).\n" % label)
            return _seat("no_credit", reason=r.get("reason"), retry_at=r.get("retry_at"), now=now)

        # 6. Probe availability for the honest record + the soft "you have it, use it" nudge.
        pr = mod.probe()
        if pr.get("status") == mod.READY:
            loud = (mode == "on")
            msg = ("%s is AVAILABLE and this is %s — run it and pass --%s-verdict "
                   "pass|concerns|fail (recorded as available-but-not-run).\n" % (label, tier, label))
            sys.stderr.write(("NUDGE: " + msg) if loud else ("%s: " % label + msg))
            return _seat("skipped", reason="available_not_run", now=now, skip_ack=skip_ack,
                         version=pr.get("version"), auth_source=pr.get("auth_source"))
        if pr.get("status") == mod.PRESENT_NOAUTH:
            sys.stderr.write("%s: installed but not authenticated — continuing without it.%s\n"
                             % (label, (" " + fix_hint) if fix_hint else ""))
            return _seat("unavailable", reason="present_noauth", now=now)
        sys.stderr.write("%s: not installed — continuing without it.\n" % label)
        return _seat("unavailable", reason="missing", now=now)
    except Exception as e:   # the cycle must NEVER fail because of a best-effort reviewer
        try:
            sys.stderr.write("%s: seat error (%s) — continuing without it.\n" % (label, str(e)[:80]))
        except Exception:
            pass
        return _seat("unavailable", reason="seat_error", now=now)


def _codex_review_seat(zd, args, tier):
    """The codex seat (best-effort; never gates). [L13/graceful-codex]"""
    return _panel_seat(zd, tier, codex, "codex",
                       getattr(args, "codex", "auto"), getattr(args, "codex_verdict", None),
                       getattr(args, "codex_summary", ""), getattr(args, "codex_error", None),
                       getattr(args, "codex_retry_at", None),
                       fix_hint="Run `codex login` or drop a token at ~/.zaude/secrets/codex.",
                       skip_ack=getattr(args, "skip_codex_ack", None))


def _opencode_review_seat(zd, args, tier):
    """The OpenCode seat — a third, MODEL-DIVERSE best-effort reviewer (provider-agnostic). Same
    contract as codex: never gates, never raises. [L13/graceful external reviewers]"""
    return _panel_seat(zd, tier, opencode, "opencode",
                       getattr(args, "opencode", "auto"), getattr(args, "opencode_verdict", None),
                       getattr(args, "opencode_summary", ""), getattr(args, "opencode_error", None),
                       getattr(args, "opencode_retry_at", None),
                       fix_hint="Run `opencode auth login` to configure a provider.",
                       skip_ack=getattr(args, "skip_opencode_ack", None))


def _kimi_review_seat(zd, args, tier):
    """The Kimi seat — a fourth, MODEL-DIVERSE best-effort reviewer (Moonshot, model
    `kimi-for-coding`). Same contract as codex/opencode: never gates, never raises. [L13/graceful
    external reviewers]"""
    return _panel_seat(zd, tier, kimi, "kimi",
                       getattr(args, "kimi", "auto"), getattr(args, "kimi_verdict", None),
                       getattr(args, "kimi_summary", ""), getattr(args, "kimi_error", None),
                       getattr(args, "kimi_retry_at", None),
                       fix_hint="Run `kimi login` to authenticate.",
                       skip_ack=getattr(args, "skip_kimi_ack", None))


def _glm_review_seat(zd, args, tier):
    """The GLM seat — a fifth, MODEL-DIVERSE best-effort reviewer (Zhipu/z.ai GLM, run via the
    claude-code drop-in pointed at z.ai). Same contract as codex/opencode/kimi: never gates, never
    raises. [L13/graceful external reviewers]"""
    return _panel_seat(zd, tier, glm, "glm",
                       getattr(args, "glm", "auto"), getattr(args, "glm_verdict", None),
                       getattr(args, "glm_summary", ""), getattr(args, "glm_error", None),
                       getattr(args, "glm_retry_at", None),
                       fix_hint="Drop a z.ai token at ~/.zaude/secrets/zai (or set ZAI_API_KEY).",
                       skip_ack=getattr(args, "skip_glm_ack", None))


# Seats whose 'skipped' state means the reviewer WAS AVAILABLE (or deliberately turned off) and so
# the model-diverse review actually happened-not-at-all — these are the skips that must be either RUN
# or explicitly ACKNOWLEDGED before a CLEAN high-risk review can be recorded. (missing/present_noauth/
# no_credit/unavailable/seat_error mean the reviewer was genuinely UN-runnable; low_risk means the
# panel wasn't engaged; used means it ran — none of those is a silently-skipped available reviewer.)
_BLOCKING_SKIP_REASONS = {"off", "never", "available_not_run"}


def panel_skip_block(tier, seats):
    """PURE (no I/O, never raises): the panel-enforcement gate. Returns (seat_name, reason) for the
    FIRST available-but-UN-acknowledged skip that must block a CLEAN high-risk review, else None.

    The diagnosed hole: a clean review (unresolved_critical_high == 0) could be recorded with the
    model-diverse seats SILENTLY skipped (off / never / available_but_not_run) — so /review and /ship
    passed though no diverse reviewer ever looked. This closes it WITHOUT spawning anything: a seat
    that was available-but-skipped at T3/T4 must be RUN (pass a verdict) or DELIBERATELY acknowledged
    (skip_ack). Deterministic order: codex, opencode, kimi, glm (first offender wins)."""
    if tier not in gates.HIGH_RISK:
        return None
    for name in ("codex", "opencode", "kimi", "glm"):
        seat = (seats or {}).get(name) or {}
        if (seat.get("outcome") == "skipped"
                and seat.get("reason") in _BLOCKING_SKIP_REASONS
                and not seat.get("skip_ack")):
            return (name, seat.get("reason"))
    return None
