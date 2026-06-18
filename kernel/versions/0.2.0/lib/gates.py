"""
gates.py (v0.2.0) — declared gates over a GateContext [B2].

A gate is `fn(ctx) -> GateResult`. evaluate() runs the registry, first deny wins, and applies
WAIVERS: if the deciding gate is waived (an operator-approved `/waive` row in the trace) the
deny is downgraded to allow — but the use is still recorded. This is what makes "skip the gate"
possible only via an explicit, logged waiver (vs v1, where skipping is silent). [L1.4]

The hook matcher now includes Bash (and NotebookEdit), so `protect_zaude` / `design_before_impl`
have Bash counterparts (`*_bash`) that catch a Bash file-write which would otherwise SILENTLY
evade the Edit/Write gates (architecture-review finding A). The Bash write detectors are HEURISTIC
TRIPWIRES for the accidental/naive case — NOT a boundary against a determined Bash user (who can
reach the key and the shell); see docs/18-threat-model.md for the honest scope.
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

# Bash WRITE tripwires (finding A): the hook also matches Bash, so a Bash file-write can no longer
# silently evade the Edit/Write gates. These are HEURISTIC TRIPWIRES for the ACCIDENTAL/naive case
# (a determined Bash user has other escapes — see docs/18-threat-model.md); they detect a write that
# TARGETS a .zaude/ path or a source file, not merely a command that mentions one (so `cat .zaude/x`
# or `cat app.ts` read-only is not flagged, and the kernel's own `zaude` CLI is never flagged).
_SRC_EXT_ALT = "|".join(e.lstrip(".") for e in SRC_EXT)
# Only verbs whose mere involvement with a .zaude path is UNAMBIGUOUSLY a mutation of it (delete /
# move-out / move-in / shrink). Read-capable verbs (cp/dd/tee/chmod/chown/ln/install) are OMITTED:
# .zaude could be their SOURCE (`cp .zaude/x /tmp`, `dd if=.zaude`, `tee /tmp < .zaude`), and since
# this gate is NOT waivable, flagging a legit read would be a hard false-deny. [codex review]
_ZAUDE_WRITE_RE = re.compile(
    r">>?\s*['\"]?[^\s|;&<>]*\.zaude(?:[\\/]|\b)"                          # redirect INTO .zaude (write)
    r"|\b(?:rm|mv|truncate|shred|rmdir)\b[^|;&\n]*?\.zaude(?:[\\/]|\b)"    # unambiguous mutator -> .zaude
    r"|\bsed\b[^|;&\n]*-i[^|;&\n]*?\.zaude(?:[\\/]|\b)",                   # in-place edit -> .zaude
    re.IGNORECASE,
)
_SRC_WRITE_RE = re.compile(
    r"(?:>>?\s*['\"]?[^\s|;&<>]*|(?:\btee\b|\bsed\b[^|;&\n]*-i)[^|;&\n]*?)"
    r"\.(?:%s)\b" % _SRC_EXT_ALT,
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


def protect_zaude_bash(ctx):
    """Bash counterpart of protect_zaude (finding A): a Bash command that WRITES/DELETES a path under
    .zaude/ is denied, NOT waivable. The hook now matches Bash, so this can fire. HEURISTIC TRIPWIRE
    for the accidental/naive case (a determined Bash user has other escapes — docs/18); the kernel's
    own `zaude` CLI writes .zaude via its atomic writer and is NOT flagged (no write-op targets the
    state dir in a launcher invocation)."""
    if ctx.tool == "Bash" and ctx.command and _ZAUDE_WRITE_RE.search(ctx.command):
        return GateResult("deny",
                          "protected: that Bash command writes under .zaude/ (the signed source of "
                          "truth). Use `zaude` commands; never write .zaude/ directly.", waivable=False)
    return GateResult("allow")


def design_before_impl_bash(ctx):
    """Bash counterpart of design_before_impl (finding A): at high risk (T3/T4) before design+approve,
    a Bash command that writes to a SOURCE file is denied (waivable, shares the design-before-impl
    waiver). HEURISTIC TRIPWIRE for the accidental case — docs/18."""
    if (ctx.tool == "Bash" and ctx.command
            and ctx.state.get("risk_tier") in HIGH_RISK
            and ctx.current not in _state.SRC_EDIT_ALLOWED_FROM
            and _SRC_WRITE_RE.search(ctx.command)):
        return GateResult(
            "deny",
            "design-before-impl: that Bash command writes source at risk %s before design + "
            "/approve. Next: /design → /approve (or use the Edit tool). Waiver: /waive "
            "design-before-impl <reason>." % ctx.state.get("risk_tier"))
    return GateResult("allow")


# a `/waive design-before-impl` covers BOTH the Edit and the Bash source-write gate (same intent).
design_before_impl_bash.waiver_id = "design_before_impl"

GATES = [protect_zaude, protect_zaude_bash, design_before_impl, design_before_impl_bash,
         deploy_needs_release_token]


def evaluate(projection, tool, tool_input, zaude_dir):
    """Run all gates; first deny wins. A deny on a WAIVED, waivable gate becomes an allow
    (recorded as 'allow-waived'). A gate may set `.waiver_id` to SHARE a waiver with another gate
    (the Bash source-write gate shares design_before_impl's). Returns (decision, reason, gate_name)."""
    ctx = GateContext(projection, tool, tool_input, zaude_dir)
    # Normalize so `/waive design-before-impl` and `design_before_impl` both match the gate id. [codex-MED]
    waived = {w.replace("-", "_") for w in (projection.get("waived_gates") or set())}
    for g in GATES:
        res = g(ctx)
        if res["decision"] == "deny":
            wid = getattr(g, "waiver_id", g.__name__)
            if res["waivable"] and wid in waived:
                return ("allow-waived", "waived: " + wid, g.__name__)
            return ("deny", res["reason"], g.__name__)
    return ("allow", "", "")
