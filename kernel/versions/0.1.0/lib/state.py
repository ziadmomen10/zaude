"""
state.py — the (skeleton subset of the) workflow state machine.

The full machine is 14 states (L1.1). The walking skeleton proves the mechanism with a
4-state subset: Intake -> Clarified -> Designed -> Implemented. state is DERIVED from the
trace (project_state), never stored authoritatively. [R3]
"""

STATES = ["Intake", "Clarified", "Designed", "Implemented"]

# Legal forward transitions (skeleton).
TRANSITIONS = {
    "Intake": {"Clarified"},
    "Clarified": {"Designed"},
    "Designed": {"Implemented"},
    "Implemented": set(),
}

# States in which editing source is permitted by the design-before-impl gate.
SRC_EDIT_ALLOWED_FROM = {"Designed", "Implemented"}


class StateForged(Exception):
    """A transition row that does not follow legally from the prior state. The trace was
    hand-appended to forge state. The hook treats this like corruption: fail-closed."""


def project_state(rows):
    """Derive the current state by VALIDATING replay (A1). Each transition row must declare
    `from` == the current state AND be a legal transition; an illegal row means the trace was
    forged (e.g. someone appended `{"kind":"transition","to":"Designed"}` to skip the gate),
    so we raise StateForged rather than silently advancing. [sec-H2, arch-C1, codex-CRIT]"""
    st = "Intake"
    for r in rows:
        if r.get("kind") != "transition":
            continue
        frm = r.get("from")
        to = r.get("to")
        if to not in STATES:
            raise StateForged("transition to unknown state %r" % (to,))
        if frm != st or not can_transition(st, to):
            raise StateForged("illegal transition %r -> %r (current=%r)" % (frm, to, st))
        st = to
    return st


def can_transition(frm, to):
    return to in TRANSITIONS.get(frm, set())


def next_states(frm):
    return sorted(TRANSITIONS.get(frm, set()))
