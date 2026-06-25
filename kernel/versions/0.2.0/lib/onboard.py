"""
onboard.py (v0.2.0) — project scaffolding [L11], local form.

Scaffolds a project INTO the framework: a vault folder (CLAUDE.md / current-state.md /
decisions.md / open-questions.md / spec.md + memory index + sessions), and a git repo. The
.zaude state machine is initialized by the caller (cli.cmd_onboard). Idempotent — re-running
adopts existing files. GitHub push is a token-gated extra (not done offline). stdlib only.
"""
import os
import subprocess

_VAULT_FILES = {
    "CLAUDE.md": "# {slug} — project instructions\n\n**Stack:** {stack}\n\nRead this + "
                 "decisions.md + current-state.md at session start.\n",
    "current-state.md": "# Current state — {slug}\n\n_Initialized. No work in flight yet._\n",
    "decisions.md": "# Decisions (append-only)\n\n_New decisions appended at the bottom with dates._\n",
    "open-questions.md": "# Open questions — {slug}\n",
    "spec.md": "# Spec — {slug}\n\n{intent}\n",
}


def scaffold_vault(root, slug, stack, intent=""):
    vd = os.path.join(root, "vault", slug)
    os.makedirs(os.path.join(vd, "memory"), exist_ok=True)
    os.makedirs(os.path.join(vd, "sessions"), exist_ok=True)
    created = []
    for name, tmpl in _VAULT_FILES.items():
        p = os.path.join(vd, name)
        if not os.path.exists(p):                       # idempotent: adopt, don't clobber
            with open(p, "w", encoding="utf-8") as f:
                f.write(tmpl.format(slug=slug, stack=stack, intent=intent))
            created.append(name)
    mi = os.path.join(vd, "memory", "memory-index.jsonl")
    if not os.path.exists(mi):
        open(mi, "w", encoding="utf-8").close()
        created.append("memory/memory-index.jsonl")
    return vd, created


# .zaude operational / sidecar state that must never be git-tracked (the signed trace + project
# marker ARE tracked; these are local health/secret/scratch files). opencode.json was missing from
# the original fresh-init list. [ZI-001 + codex review HIGH]
_ZAUDE_IGNORE = (".zaude/.lock", ".zaude/*.tmp.*", ".zaude/codex.json", ".zaude/opencode.json",
                 ".zaude/kimi.json", ".zaude/glm.json", ".zaude/persona/", ".zaude/memory/",
                 "__pycache__/")


def ensure_gitignore(root):
    """Ensure every .zaude sidecar entry is git-ignored — for FRESH and EXISTING git projects alike
    (ZI-001: an existing-git project previously got NO ignore entries because git_init returned
    early), appending only the MISSING lines idempotently. Never raises. Returns the lines added."""
    gi = os.path.join(root, ".gitignore")
    try:
        existing = ""
        if os.path.exists(gi):
            with open(gi, "r", encoding="utf-8") as f:
                existing = f.read()
        have = set(existing.splitlines())
        missing = [e for e in _ZAUDE_IGNORE if e not in have]
        if missing:
            sep = "" if (existing == "" or existing.endswith("\n")) else "\n"
            with open(gi, "a", encoding="utf-8") as f:
                f.write(sep + "\n".join(missing) + "\n")
        return missing
    except Exception:
        return []


def git_init(root):
    """git init if needed, then ALWAYS ensure the .zaude sidecar gitignore entries exist (fresh OR
    existing git). Returns True iff a new repo was initialized. Never raises. [ZI-001]"""
    new = False
    if not os.path.isdir(os.path.join(root, ".git")):
        try:
            subprocess.run(["git", "init", "-q", root], capture_output=True, timeout=20)
            new = True
        except Exception:
            new = False
    ensure_gitignore(root)
    return new
