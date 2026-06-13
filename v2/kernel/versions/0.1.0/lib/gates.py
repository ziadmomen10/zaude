"""
gates.py — deterministic tool gates. The skeleton ships ONE gate: design-before-impl.

A gate is a pure function (state, tool, target) -> (decision, reason). The PreToolUse
hook calls it; in 'enforce' mode a 'deny' blocks the tool, in 'shadow' mode it is only
logged. [D14]
"""
import os
from . import state as _state

# Source-file extensions the design gate protects. (Config/docs/tests are not "source"
# for the skeleton; the full kernel reads these path-patterns from gate-policy.json — B6.)
SRC_EXT = (
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".pyi", ".pyw", ".go", ".rs",
    ".java", ".rb", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx", ".cs", ".php",
    ".vue", ".svelte", ".swift", ".kt", ".scala", ".sql",
)

# Tools that mutate files. NOTE: Bash can also mutate (redirects/sed -i) — that is a
# Phase-2 residual (B9); the skeleton closes the file-tool path incl. MultiEdit. [codex, cr-H5]
MUTATING_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _normalize_basename(path):
    """Strip Windows filename tricks that resolve to a different real file: trailing dots
    and spaces (Win32 strips them), and NTFS alternate-data-stream suffixes (file:stream).
    [sec-H1, cr-H4, codex-HIGH]"""
    base = os.path.basename(path.replace("\\", "/"))
    base = base.split(":", 1)[0]          # drop ADS  foo.ts:stream -> foo.ts
    base = base.rstrip(" .")              # drop trailing dots/spaces  foo.ts. -> foo.ts
    return base.lower()


def is_source(path):
    if not path or not isinstance(path, str):
        return False
    # 1) lexical check on the normalized basename
    if _normalize_basename(path).endswith(SRC_EXT):
        return True
    # 2) if the path exists, resolve symlinks/junctions and re-check the real target
    try:
        real = os.path.realpath(path)
        if os.path.exists(real) and _normalize_basename(real).endswith(SRC_EXT):
            return True
    except Exception:
        pass
    return False


def _under(target, zaude_dir):
    """True if target resolves to somewhere inside the project's own .zaude/ tree."""
    if not target or not zaude_dir:
        return False
    try:
        rt = os.path.normcase(os.path.realpath(target))
        rz = os.path.normcase(os.path.realpath(zaude_dir))
        return rt == rz or rt.startswith(rz + os.sep)
    except Exception:
        return False


def protect_zaude(current_state, tool, target, zaude_dir):
    """The kernel's own trace/state/project files are sacred: a mutating tool must never
    write under .zaude/ (that would let the model forge state). Always denied. [A1]"""
    if tool in MUTATING_TOOLS and _under(target, zaude_dir):
        return ("deny",
                "protected: .zaude/ is the kernel's source of truth and cannot be edited by "
                "tools. Use `zaude` commands to advance state.")
    return ("allow", "")


def design_before_impl(current_state, tool, target, zaude_dir):
    """Block source Edit/Write until the project has reached Designed. [L1.3]"""
    if tool in MUTATING_TOOLS and is_source(target):
        if current_state not in _state.SRC_EDIT_ALLOWED_FROM:
            return (
                "deny",
                ("design-before-impl: state=%s — a design.json + a /design transition is "
                 "required before editing source. Next: /design. Waiver: /waive "
                 "design-before-impl <reason>." % current_state),
            )
    return ("allow", "")


# The skeleton gate registry. The full kernel adds evidence/built-artifact/health/drift/
# secret-DLP/SBOM/migration/closure gates here (and moves to a GateContext — B2).
GATES = [protect_zaude, design_before_impl]


def evaluate(current_state, tool, target, zaude_dir=None):
    """Run all gates; first deny wins. Returns (decision, reason, gate_name)."""
    for g in GATES:
        decision, reason = g(current_state, tool, target, zaude_dir)
        if decision == "deny":
            return ("deny", reason, g.__name__)
    return ("allow", "", "")
