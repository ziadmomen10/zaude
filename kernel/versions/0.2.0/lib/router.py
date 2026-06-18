"""
router.py (v0.2.0) — INTENT DETECTION: map a natural-language request to the right Zaude command,
so the operator says WHAT they want instead of remembering WHICH /command. This is the "C++ on C"
front door [architecture review, Claude+codex 2026-06-17].

Hybrid by design: the LLM driver is the semantic front door (it reads intent and acts); this kernel
module is the deterministic registry + scorer + SAFETY MODEL that the driver (and `zaude route`)
consult so routing is auditable and never misfires on destructive actions. Leaf lib (no trace/state
import, like keys.py). Never raises. stdlib only.

Safety classes drive whether a routed command may auto-run:
  AUTO    — safe / read-only -> may auto-execute.
  PROPOSE — mutating workflow step -> propose, then confirm.
  CONFIRM — destructive / irreversible-ish -> ALWAYS hard-confirm, regardless of confidence.
"""
import re

AUTO = "auto"
PROPOSE = "propose"
CONFIRM = "confirm"

# Per-command routing metadata. Kernel source of truth (like gates.HIGH_RISK); policy.json carries
# the human command catalog. triggers = phrases/keywords; requires_state = lifecycle precondition;
# destructive = needs an explicit destructive verb + a hard confirm.
ROUTES = {
    # ---- read-only / safe (AUTO) ----
    "status":      {"safety": AUTO, "triggers": ["where am i", "status", "current state",
                                                  "what is going on", "show state"]},
    "next":        {"safety": AUTO, "triggers": ["what now", "what next", "next step",
                                                  "what should i do", "what do i do"]},
    "doctor":      {"safety": AUTO, "triggers": ["health", "is everything ok", "diagnose",
                                                 "check the project", "sanity check"]},
    "dod":         {"safety": AUTO, "triggers": ["are we done", "definition of done", "is it done"]},
    "codex":       {"safety": AUTO, "triggers": ["codex status", "is codex available", "codex"]},
    "agents":      {"safety": AUTO, "triggers": ["which agents", "agents installed", "missing agents"]},
    "board":       {"safety": AUTO, "triggers": ["show the board", "backlog", "the board", "intake column"]},
    "trace-verify": {"safety": AUTO, "triggers": ["verify the trace", "is the trace intact", "audit integrity"]},
    "route":       {"safety": AUTO, "triggers": ["which command", "what command", "route this"]},

    # ---- mutating workflow (PROPOSE) ----
    "onboard":     {"safety": PROPOSE, "triggers": ["onboard", "new project", "set up zaude",
                                                    "start a project", "scaffold"]},
    "clarify":     {"safety": PROPOSE, "triggers": ["clarify", "requirements", "acceptance criteria",
                                                    "what we need"], "requires_state": ["Intake"]},
    "prioritize":  {"safety": PROPOSE, "triggers": ["prioritize", "priority", "what matters most"],
                    "requires_state": ["Clarified"]},
    "plan":        {"safety": PROPOSE, "triggers": ["plan", "ordered steps", "break it down", "sequence"],
                    "requires_state": ["Prioritized"]},
    "design":      {"safety": PROPOSE, "triggers": ["design", "architecture", "technical approach",
                                                    "how should we build", "before implementation"],
                    "requires_state": ["Planned"]},
    "classify-risk": {"safety": PROPOSE, "triggers": ["risk", "how risky", "classify risk", "risk tier"],
                      "requires_state": ["Designed"]},
    "approve":     {"safety": PROPOSE, "triggers": ["approve", "sign off", "go ahead", "approved"],
                    "requires_state": ["RiskClassified"]},
    "implement":   {"safety": PROPOSE, "triggers": ["implement", "start coding", "build it", "write the code"],
                    "requires_state": ["Approved"]},
    "test":        {"safety": PROPOSE, "triggers": ["test", "run the tests", "record test results"],
                    "requires_state": ["Implemented"]},
    "review":      {"safety": PROPOSE, "triggers": ["review", "run the panel", "code review", "review the diff"],
                    "requires_state": ["Tested"]},
    "verify":      {"safety": PROPOSE, "triggers": ["verify", "verification", "confirm it works"],
                    "requires_state": ["Reviewed"]},
    "shippable":   {"safety": PROPOSE, "triggers": ["shippable", "ready to ship", "quality gate"],
                    "requires_state": ["Verified"]},
    "fast":        {"safety": PROPOSE, "triggers": ["small fix", "tiny", "quick", "trivial", "just do it",
                                                    "fast lane"]},
    "intake":      {"safety": PROPOSE, "triggers": ["idea", "drop an idea", "note this", "backlog this"]},
    "promote":     {"safety": PROPOSE, "triggers": ["promote", "turn into a feature", "work on it"]},
    "pm-sync":     {"safety": PROPOSE, "triggers": ["sync the board", "push to github", "update the board"]},
    "pm-init":     {"safety": PROPOSE, "triggers": ["set up the board", "create the github project"]},
    "pm-mirror":   {"safety": PROPOSE, "triggers": ["mirror the board", "backlog to vault"]},
    "vault-sync":  {"safety": PROPOSE, "triggers": ["update the vault", "refresh current state",
                                                    "project the trace to the vault", "update decisions"]},
    "vault-push":  {"safety": PROPOSE, "triggers": ["push the vault", "back up the vault"]},
    "runner":      {"safety": PROPOSE, "triggers": ["ci", "github actions", "set up a runner", "pipeline"]},

    # ---- destructive / irreversible-ish (CONFIRM) ----
    "ship":        {"safety": CONFIRM, "triggers": ["ship", "release", "deploy", "go live", "publish"],
                    "requires_state": ["Shippable"], "destructive": True},
    "fast-ship":   {"safety": CONFIRM, "triggers": ["ship the small fix", "quick ship", "fast ship"],
                    "destructive": True},
    "close":       {"safety": CONFIRM, "triggers": ["close it out", "close the work", "wrap up"],
                    "requires_state": ["Released"], "destructive": True},
    "waive":       {"safety": CONFIRM, "triggers": ["waive", "bypass the gate", "override the gate", "skip the gate"],
                    "destructive": True},
    "repair":      {"safety": CONFIRM, "triggers": ["repair", "rebuild state", "fix the state"], "destructive": True},
    "pm-pull":     {"safety": CONFIRM, "triggers": ["pull from github", "import board edits"], "destructive": True},
}

# An explicit destructive verb must appear for a CONFIRM/destructive command to score positively.
_DESTRUCTIVE_VERBS = ("ship", "release", "deploy", "publish", "go live", "waive", "bypass",
                      "override", "skip", "close", "repair", "rebuild", "pull", "reset")

# Confidence bands (codex).
BAND_CONFIDENT = 0.78
BAND_PLAUSIBLE = 0.55


def _norm(t):
    return re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())


def _score(text, meta, current_state):
    nt = " " + _norm(text) + " "
    words = set(nt.split())
    s = 0.0
    # exact trigger phrase (best single hit)
    if any(_norm(trig) in nt for trig in meta["triggers"]):
        s += 0.40
    # keyword overlap with the trigger vocabulary
    trig_words = set(_norm(" ".join(meta["triggers"])).split())
    s += min(0.20, 0.05 * len(words & trig_words))
    # lifecycle compatibility
    rs = meta.get("requires_state")
    if rs and current_state:
        s += 0.15 if current_state in rs else -0.35
    # destructive: require an explicit destructive verb, else heavily penalize
    if meta.get("destructive") and not any(v in nt for v in _DESTRUCTIVE_VERBS):
        s -= 0.50
    return s


def route(text, current_state=None):
    """Return {intent, command, confidence, mode, safety, reason, blocked_by, alternates}. NEVER
    raises. `mode` ∈ {auto, propose, confirm, ambiguous} — the driver uses it to decide whether to
    run, ask, or list options. A CONFIRM/destructive command is NEVER 'auto', whatever the score."""
    try:
        scored = []
        for name, meta in ROUTES.items():
            sc = _score(text, meta, current_state)
            if sc > 0:
                scored.append((round(min(sc, 1.0), 2), name, meta))
        scored.sort(key=lambda x: (-x[0], x[1]))
        if not scored:
            return {"intent": None, "command": None, "confidence": 0.0, "mode": "ambiguous",
                    "safety": None, "reason": "no command matched the request",
                    "blocked_by": [], "alternates": []}
        conf, name, meta = scored[0]
        safety = meta["safety"]
        blocked = []
        rs = meta.get("requires_state")
        if rs and current_state and current_state not in rs:
            blocked.append("needs state %s (currently %s)" % ("/".join(rs), current_state))
        # mode = confidence band x safety class. A read-only AUTO command may auto-run at merely
        # PLAUSIBLE confidence (being wrong just shows status/next — harmless); a destructive
        # CONFIRM command is NEVER auto, whatever the score; everything else proposes.
        if conf < BAND_PLAUSIBLE:
            mode = "ambiguous"
        elif safety == CONFIRM or meta.get("destructive"):   # structural: destructive => confirm,
            mode = "confirm"                                  # never dependent on perfect metadata
        elif safety == AUTO:
            mode = "auto"
        else:
            mode = "propose"
        return {"intent": name, "command": name, "confidence": conf, "mode": mode,
                "safety": safety,
                "reason": "matched %s (%s)" % (name, safety),
                "blocked_by": blocked,
                "alternates": [{"command": n, "confidence": c} for c, n, _ in scored[1:3]]}
    except Exception as e:
        return {"intent": None, "command": None, "confidence": 0.0, "mode": "ambiguous",
                "safety": None, "reason": "router error: %s" % str(e)[:60],
                "blocked_by": [], "alternates": []}
