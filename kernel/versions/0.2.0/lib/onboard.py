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


def git_init(root):
    if os.path.isdir(os.path.join(root, ".git")):
        return False
    try:
        subprocess.run(["git", "init", "-q", root], capture_output=True, timeout=20)
        gi = os.path.join(root, ".gitignore")
        if not os.path.exists(gi):
            with open(gi, "w", encoding="utf-8") as f:
                f.write(".zaude/.lock\n.zaude/*.tmp.*\n.zaude/codex.json\n"
                        ".zaude/persona/\n__pycache__/\n")
        return True
    except Exception:
        return False
