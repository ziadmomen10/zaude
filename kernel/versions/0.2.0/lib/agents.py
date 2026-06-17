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
