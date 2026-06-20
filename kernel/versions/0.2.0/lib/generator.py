"""
generator.py (L6) — render slash-commands + capability agents + the settings.json hook block from
the canonical policy.json into a STAGING dir (~/.zaude/generated/). Never writes the live ~/.claude
config — `zaude install` does that, explicitly, with a snapshot. Each file is stamped in a manifest
(content sha + policy sha) for drift/parity checks. stdlib only.
"""
import os
import json
import hashlib

import re

HOME = os.path.expanduser("~")
POLICY = os.path.join(HOME, ".zaude", "policy", "policy.json")
STAGING = os.path.join(HOME, ".zaude", "generated")
MARKER = "<!-- zaude-generated: do not edit; regenerate via `zaude gen` -->"
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")  # safe file stems — no path escapes

_CMD_TMPL = """---
description: {summary}
---
Zaude lifecycle step **{name}** (kernel command `{cli}`). {summary}

Do this:
1. If unsure of the flags, run `python "$HOME/.zaude/bin/zaude.py" {cli} --help`.
2. Build the command from the user's request ($ARGUMENTS) and run it in the project directory:
   `python "$HOME/.zaude/bin/zaude.py" {cli} <flags>`
3. Report the state transition / gate result concisely. If the kernel REFUSES (wrong state, a gate,
   or missing evidence), surface the next legal step it printed and STOP — never bypass a gate.
   Use `/zwaive` only with a real, recorded reason. The signed Zaude trace is the source of truth.
"""

_AGENT_TMPL = """---
name: {name}
description: {desc}
model: {model}
tools: Read, Grep, Glob, Bash
---
{brief}

You are a Zaude **{name}** ({capability}). Produce `{produces}` when applicable. Be terse,
evidence-driven, and adversarial. Never accept a claim without backing.
"""


def load_policy(path=POLICY):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_command(c):
    # A command may carry a custom `body`: full markdown for an ORCHESTRATION command (e.g. /zwrap)
    # that does more than wrap one CLI call. The body is emitted VERBATIM (no .format) so its prose
    # can contain braces/placeholders safely. Commands without a body get the thin CLI wrapper.
    if "body" in c:
        body = c["body"]
        if not body.strip():   # a half-deleted/blank body must FAIL, not silently fall through
            raise ValueError("empty body for command %r in policy" % c.get("name"))
        head = "---\ndescription: %s\n---\n" % c.get("summary", "")
        return head + body.rstrip("\n") + "\n\n" + MARKER + "\n"
    return _CMD_TMPL.format(name=c["name"], cli=c["cli"], summary=c.get("summary", "")) + "\n" + MARKER + "\n"


def render_agent(a):
    return _AGENT_TMPL.format(name=a["name"], desc=a.get("brief", "")[:120],
                              model=a.get("model", "inherit"), brief=a.get("brief", ""),
                              capability=a.get("capability", "readonly"),
                              produces=a.get("produces", "—")) + "\n" + MARKER + "\n"


def render_hook_block(policy):
    """Render settings.json hook block(s) for EVERY event in policy.hooks -> {event: block}.
    A block carries 'matcher' only when the policy entry has one (PreToolUse is tool-matched;
    UserPromptSubmit is not). [Zaude 3 P0b: the front-door hook must be reproducible too.]"""
    out = {}
    for event, h in policy.get("hooks", {}).items():
        hooks = [{"type": "command", "command": h["command"], "timeout": h.get("timeout", 10)}]
        out[event] = ({"matcher": h["matcher"], "hooks": hooks}
                      if h.get("matcher") is not None else {"hooks": hooks})
    return out


def generate(out_dir=STAGING, policy_path=POLICY):
    raw = load_policy(policy_path)
    policy = json.loads(raw)
    psha = _sha(raw)
    cmd_dir = os.path.join(out_dir, "commands")
    agent_dir = os.path.join(out_dir, "agents")
    os.makedirs(cmd_dir, exist_ok=True)
    os.makedirs(agent_dir, exist_ok=True)
    manifest = {"policy_sha": psha, "files": []}

    def emit(path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        manifest["files"].append({"path": os.path.relpath(path, out_dir), "sha": _sha(text)})

    for c in policy.get("commands", []):
        if not _NAME_RE.match(c.get("name", "")):
            raise ValueError("unsafe command name %r in policy" % c.get("name"))
        emit(os.path.join(cmd_dir, c["name"] + ".md"), render_command(c))
    for a in policy.get("agents", []):
        if not _NAME_RE.match(a.get("name", "")):
            raise ValueError("unsafe agent name %r in policy" % a.get("name"))
        emit(os.path.join(agent_dir, a["name"] + ".md"), render_agent(a))
    hb = render_hook_block(policy)
    emit(os.path.join(out_dir, "hook-block.json"), json.dumps(hb, indent=2))

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return {"out_dir": out_dir, "policy_sha": psha,
            "commands": len(policy.get("commands", [])), "agents": len(policy.get("agents", [])),
            "files": len(manifest["files"])}
