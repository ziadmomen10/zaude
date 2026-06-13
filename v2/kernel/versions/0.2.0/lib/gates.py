"""
gates.py (v0.2.0) — declared gates over a GateContext [B2].

A gate is `fn(ctx) -> GateResult`. evaluate() runs the registry, first deny wins, and applies
WAIVERS: if the deciding gate is waived (an operator-approved `/waive` row in the trace) the
deny is downgraded to allow — but the use is still recorded. This is what makes "skip the gate"
possible only via an explicit, logged waiver (vs v1, where skipping is silent). [L1.4]
"""
import os
import re
from . import state as _state

SRC_EXT = (
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".pyi", ".pyw", ".go", ".rs",
    ".java", ".rb", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx", ".cs", ".php",
    ".vue", ".svelte", ".swift", ".kt", ".scala", ".sql",
)
MUTATING_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# Conservative deploy/publish command signatures (Bash). Blocked until /ship issues a token.
_DEPLOY_RE = re.compile(
    r"(docker\s+push|kubectl\s+(apply|rollout)|terraform\s+apply|helm\s+(up|install)|"
    r"serverless\s+deploy|vercel\s+.*--prod|fly(ctl)?\s+deploy|npm\s+publish|"
    r"\bci-deploy|\bdeploy\.sh|supabase\s+functions\s+deploy|git\s+push\s+.*\bprod)",
    re.IGNORECASE,
)


class GateContext(object):
    def __init__(self, projection, tool, tool_input, zaude_dir):
        self.state = projection                       # the folded Projection
        self.current = projection.get("current_state")
        self.tool = tool
        self.tool_input = tool_input or {}
        self.zaude_dir = zaude_dir
        self.target = (self.tool_input.get("file_path")
                       or self.tool_input.get("notebook_path") or "")
        self.command = self.tool_input.get("command") or ""


def GateResult(decision, reason="", waivable=True):
    return {"decision": decision, "reason": reason, "waivable": waivable}


# ---------- helpers ----------
def _norm_base(path):
    base = os.path.basename(path.replace("\\", "/"))
    base = base.split(":", 1)[0].rstrip(" .")
    return base.lower()


def is_source(path):
    if not path or not isinstance(path, str):
        return False
    if _norm_base(path).endswith(SRC_EXT):
        return True
    try:
        real = os.path.realpath(path)
        if os.path.exists(real) and _norm_base(real).endswith(SRC_EXT):
            return True
    except Exception:
        pass
    return False


def _under(target, zaude_dir):
    if not target or not zaude_dir:
        return False
    try:
        rt = os.path.normcase(os.path.realpath(target))
        rz = os.path.normcase(os.path.realpath(zaude_dir))
        return rt == rz or rt.startswith(rz + os.sep)
    except Exception:
        return False


# ---------- gates ----------
def protect_zaude(ctx):
    """No tool may write the kernel's own trace/state/project files. NOT waivable. [A1]"""
    if ctx.tool in MUTATING_TOOLS and _under(ctx.target, ctx.zaude_dir):
        return GateResult("deny",
                          "protected: .zaude/ is the source of truth and cannot be edited by "
                          "tools. Use `zaude` commands.", waivable=False)
    return GateResult("allow")


# LIGHT BY DEFAULT [Deen]: design-before-impl engages ONLY for genuinely high-risk work.
# Low/medium/unclassified work codes freely (the audit trail still records everything). Only
# T3/T4 (auth, migrations, prod, security, destructive) require design+approval before code.
HIGH_RISK = {"T3", "T4"}


def design_before_impl(ctx):
    """Block source edits before design+approval ONLY for high-risk work. [L1.3, light-default]"""
    if ctx.tool in MUTATING_TOOLS and is_source(ctx.target):
        if ctx.state.get("risk_tier") in HIGH_RISK and ctx.current not in _state.SRC_EDIT_ALLOWED_FROM:
            return GateResult(
                "deny",
                "design-before-impl: this work is risk %s — high-risk changes need design + "
                "/approve before editing source. Next: /design → /approve. Waiver: /waive "
                "design-before-impl <reason>." % ctx.state.get("risk_tier"))
    return GateResult("allow")


def deploy_needs_release_token(ctx):
    """Block deploy/publish shell commands unless /ship issued a release-token. [R7]

    NOTE: regex-on-command is a HEURISTIC TRIPWIRE, not a hard security boundary — it is
    bypassable (aliases, `sh -c "$CMD"`, `make deploy`, renamed binaries). The real boundary is
    the state machine (you can't reach a token without the review→verify chain). Phase-3 replaces
    this with an allowlist of declared deploy entrypoints from gate-policy.json. [codex-HIGH, B6]"""
    if ctx.tool == "Bash" and ctx.command and _DEPLOY_RE.search(ctx.command):
        if not ctx.state.get("release_token_active"):
            return GateResult(
                "deny",
                "deploy-without-token: this looks like a deploy/publish command but no release "
                "token is active. Run the review→verify→/ship chain first. Waiver: /waive "
                "deploy-needs-release-token <reason>.")
    return GateResult("allow")


GATES = [protect_zaude, design_before_impl, deploy_needs_release_token]


def evaluate(projection, tool, tool_input, zaude_dir):
    """Run all gates; first deny wins. A deny on a WAIVED, waivable gate becomes an allow
    (recorded as 'allow-waived'). Returns (decision, reason, gate_name)."""
    ctx = GateContext(projection, tool, tool_input, zaude_dir)
    # Normalize so `/waive design-before-impl` and `design_before_impl` both match the gate id. [codex-MED]
    waived = {w.replace("-", "_") for w in (projection.get("waived_gates") or set())}
    for g in GATES:
        res = g(ctx)
        if res["decision"] == "deny":
            if res["waivable"] and g.__name__ in waived:
                return ("allow-waived", "waived: " + g.__name__, g.__name__)
            return ("deny", res["reason"], g.__name__)
    return ("allow", "", "")
