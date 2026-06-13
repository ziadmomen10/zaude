"""
state.py (v0.2.0) — the full lifecycle state machine + a SINGLE reducer [B1].

`reduce(rows)` folds the (already integrity-verified) trace into one ProjectionState that
every consumer reads — the hook, `status`, and every gate — so trace interpretation never
forks. Replay is VALIDATING: an illegal transition row raises StateForged (fail-closed). [A1]
"""
import time

STATES = [
    "Intake", "Clarified", "Prioritized", "Planned", "Designed", "RiskClassified",
    "Approved", "Implemented", "Tested", "Reviewed", "Verified", "Shippable",
    "Released", "Closed",
]

# Linear forward transitions (the happy path).
_ORDER = {s: i for i, s in enumerate(STATES)}
TRANSITIONS = {s: ({STATES[i + 1]} if i + 1 < len(STATES) else set())
               for i, s in enumerate(STATES)}

# The artifact each state's entry command must produce (command-layer gate).
REQUIRED_ARTIFACT = {
    "Clarified": "requirements.json",
    "Prioritized": "priority.json",
    "Planned": "plan.json",
    "Designed": "design.json",
    "RiskClassified": "risk.json",
    "Approved": "approval.json",
    "Implemented": "impl.json",
    "Tested": "test-results.json",
    "Reviewed": "review-ledger.json",
    "Verified": "verification.json",
    "Shippable": "shippable.json",
    "Released": "release.json",
    "Closed": "handoff.json",
}

# Source edits are allowed only once design+approval are in hand. [L1.3]
SRC_EDIT_ALLOWED_FROM = set(STATES[_ORDER["Approved"]:])


class StateForged(Exception):
    """A transition row that does not follow legally from the prior state."""


def can_transition(frm, to):
    return to in TRANSITIONS.get(frm, set())


def next_states(frm):
    return sorted(TRANSITIONS.get(frm, set()))


class Projection(dict):
    """A plain dict with attribute access for the folded state."""
    __getattr__ = dict.get


def _live(expires_at, now):
    """A scoped grant is live if it has no expiry or has not yet expired. [codex-HIGH]"""
    return expires_at is None or expires_at > now


def reduce(rows, now=None):
    """Fold the trace once. Returns a Projection. Raises StateForged on an illegal transition.
    Waiver/token expiry is enforced against `now` (defaults to wall-clock)."""
    if now is None:
        now = time.time()
    st = "Intake"
    last_transition = None
    artifacts = set()
    waived = {}            # gate -> expires_at (or None = no expiry)
    release_token = None   # {expires_at} or None
    risk_tier = None       # T0..T4 (None = unclassified = treated as low)

    for r in rows:
        kind = r.get("kind")
        if kind == "init":
            st = "Intake"
            artifacts = set()
            waived = {}
            release_token = None
            risk_tier = None
        elif kind == "risk":
            risk_tier = r.get("tier")
        elif kind == "transition":
            frm, to = r.get("from"), r.get("to")
            if to not in STATES:
                raise StateForged("transition to unknown state %r" % (to,))
            if frm != st or not can_transition(st, to):
                raise StateForged("illegal transition %r -> %r (current=%r)" % (frm, to, st))
            st = to
            last_transition = r
            if r.get("artifact"):
                artifacts.add(r["artifact"])
        elif kind == "waiver":
            g = r.get("gate")
            if g:
                waived[g] = r.get("expires_at")
        elif kind == "release_token":
            release_token = {"expires_at": r.get("expires_at"), "issued_at": r.get("ts")}
        elif kind == "release_token_consumed":
            release_token = None

    live_waivers = {g for g, exp in waived.items() if _live(exp, now)}
    token_active = release_token is not None and _live(release_token.get("expires_at"), now)
    return Projection(
        current_state=st,
        last_transition=last_transition,
        artifacts=sorted(artifacts),
        waived_gates=live_waivers,
        release_token_active=token_active,
        risk_tier=risk_tier,
    )


def project_state(rows):
    """Back-compat helper: just the current state (validating)."""
    return reduce(rows)["current_state"]
