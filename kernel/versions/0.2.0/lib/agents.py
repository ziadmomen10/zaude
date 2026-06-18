"""
agents.py (v0.2.0) — required-agent presence check [L7 / agent-reliability, finding #4.1].

Zaude's commands (the /build + review chains) DEPEND on capability agents that Zaude does NOT
generate — they are installed separately into ~/.claude/agents/. When they are missing, a command
tells the driver to invoke an agent that does not exist, which surfaces as "agents don't activate"
(the user's finding #4.1). This leaf lib (no trace/state import, like keys.py/codex.py) makes that
gap VISIBLE: it discovers installed agents and reports which required ones are missing.

ADVISORY ONLY — exactly like graceful codex: a missing agent NEVER fails the cycle or changes an
exit code (installing agents is the operator's job, and a fresh machine legitimately has none).
The value is honest visibility (via `zaude agents` and a /doctor line), not a gate. stdlib only.
"""
import os

# The external capability agents the /build + review workflow expects pre-installed. policy.json
# documents the same set under "required_agents"; this list is the runtime source of truth for the
# same reason gates.HIGH_RISK is hardcoded — the kernel does not load policy.json at runtime.
REQUIRED_AGENTS = [
    "code-reviewer", "architect-review", "security-auditor",            # the review chain
    "workflow-orchestrator", "backend-developer", "frontend-developer", "design-bridge",  # /build
]

# ---------------------------------------------------------------------------------------------
# CURATED multi-harness CATALOG (market scan 2026-06-18; see docs/17-agent-ecosystem.md). When an
# agent is MISSING we don't just print its name — we point the operator at VETTED, RANKED sources
# so the gap is ACTIONABLE. We deliberately DO NOT auto-install: packs are written for someone
# else's stack and conventions, so adoption stays a human decision — "read the prompt, check the
# tools, PIN A COMMIT, rewrite before trusting." Advisory only; never gates. [finding #4.1]
#
# The cycle runs the benchmark-best HARNESSES: the review panel runs Claude lenses (Opus 4.8 —
# #1 on SWE-bench Pro) and pairs them with BEST-EFFORT Codex (GPT-5.5 — #1 on Terminal-Bench 2.1)
# when available — the two leading agentic harnesses of 2026. The packs below add ROLE
# specialization on top of that pairing.
#
# No single pack wins, so we RANK vetted sources with their real tradeoffs:
#   (key, repo, why / strength, supports_codex, caveat)
SOURCES = [
    ("wshobson", "wshobson/agents",
     "broadest: 192 agents / 156 skills / 16 orchestrators; ships native to Claude Code AND Codex",
     True, "single-maintainer + NO versioned releases - pin a commit for reproducibility"),
    ("voltagent", "VoltAgent/awesome-claude-code-subagents",
     "community-maintained; every agent declares a MINIMAL tools field (least privilege)",
     True, "100+ Claude-focused; review each prompt before trusting"),
    ("voltagent-skills", "VoltAgent/awesome-agent-skills",
     "1000+ agent SKILLS from official dev teams + community (complementary to subagent packs)",
     True, "skills, not subagents"),
]
PRIMARY_SOURCE = SOURCES[0][1]
INSTALL_CMDS = {
    "claude": "/plugin marketplace add wshobson/agents   (then /plugin install <plugin>)",
    "codex": "npx codex-marketplace add wshobson/agents",
}
# Zaude role name -> (what it does in the cycle, the closest slug in the PRIMARY source). The slug
# can differ from Zaude's role name; the operator installs it and, if needed, aliases/rewrites it.
CATALOG = {
    "code-reviewer":         ("review: correctness, security, reliability",   "code-reviewer"),
    "architect-review":      ("review: architectural consistency",            "architect-reviewer"),
    "security-auditor":      ("review: security audit / OWASP",               "security-auditor"),
    "workflow-orchestrator": ("/build: sequence the work across steps",       "context-manager"),
    "backend-developer":     ("/build: backend / API design",                 "backend-architect"),
    "frontend-developer":    ("/build: frontend implementation",              "frontend-developer"),
    "design-bridge":         ("/build: UI/UX design rules",                   "ui-ux-designer"),
}


def guidance(missing):
    """Per-missing-agent ACTIONABLE source guidance: [(name, role, source, upstream_slug)] using the
    top-ranked source. Unknown names still get a line (generic source). Never raises."""
    out = []
    for name in (missing or []):
        role, slug = CATALOG.get(name, ("capability agent", name))
        out.append((name, role, PRIMARY_SOURCE, slug))
    return out


def agent_dirs(project_root=None):
    """User-level then project-level Claude Code agent dirs (project overrides win by union)."""
    dirs = [os.path.join(os.path.expanduser("~"), ".claude", "agents")]
    if project_root:
        dirs.append(os.path.join(project_root, ".claude", "agents"))
    return dirs


def discover_installed(project_root=None):
    """Set of installed agent names (basename minus .md) across the user + project agent dirs.
    Never raises — an unreadable/absent dir just contributes nothing."""
    found = set()
    for d in agent_dirs(project_root):
        try:
            for fn in os.listdir(d):
                if fn.endswith(".md"):
                    found.add(fn[:-3])
        except Exception:
            continue
    return found


def check(project_root=None, required=None):
    """Return {required, present, missing, installed_total}. Never raises."""
    req = list(required if required is not None else REQUIRED_AGENTS)
    installed = discover_installed(project_root)
    present = [a for a in req if a in installed]
    missing = [a for a in req if a not in installed]
    return {"required": req, "present": present, "missing": missing,
            "installed_total": len(installed)}
