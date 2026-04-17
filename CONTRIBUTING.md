# Contributing to Zaude

Thanks for your interest. This repo is small, focused, and has strong opinions — contributions are welcome in the directions that keep it that way.

---

## What's in scope

**Welcome:**
- Bug fixes in hooks, commands, or install scripts
- Cross-platform improvements (especially native Windows testing)
- Additional pattern files for common project types (React + Supabase, Rails, Django, Go services, iOS, etc.)
- Troubleshooting entries from real failure cases you've hit
- Translations of README and setup prompt
- Improvements to the example project

**Probably welcome (open an issue first):**
- New slash commands that cover a workflow the existing five don't
- New hooks for specific concerns (linting-pre-commit, language-specific guards)
- Integration with additional MCP servers

**Out of scope:**
- Forks of Claude Code itself
- Replacing the slash-command-driven model with something else
- Automating vibe coding (adding shortcuts that skip the review chain)
- IDE-specific integrations that aren't also editor-agnostic

---

## Opening a PR

1. Fork the repo.
2. Create a branch off `main` with a descriptive name (`fix/windows-install-python-path`, `add/rails-pattern`).
3. Make focused commits — one logical change per commit is ideal.
4. Update docs alongside code if your change affects user-facing behavior.
5. Test your change:
   - Hooks: run the hook manually with a mocked `stdin` JSON and verify output
   - Install scripts: run end-to-end on a clean directory
   - Patterns / docs: render on GitHub to verify Mermaid, tables, and links
6. Open the PR with:
   - A clear title (imperative: "fix Windows path handling in session-start hook")
   - A description explaining what changed and why
   - Any testing you did
   - Screenshots if UI/rendered output is affected

---

## Style

- **Markdown:** GitHub-flavored. Use tables for scannable content. Keep sections scannable.
- **Python hooks:** type annotations encouraged. Keep them single-file. Never add external dependencies — the standard library is enough.
- **Bash hooks:** `#!/bin/bash` + `set -e` when the script should fail fast; silent failures via `|| return` in the session-end script (never block session end).
- **PowerShell hooks:** parity with Bash where possible.
- **No emojis in hook code.** README and docs can use them; code should not.

---

## What makes a good pattern file

If you're contributing to `templates/vault/03-patterns/`:

- Each rule should fit on one laptop screen
- Every rule has a **Problem** statement, **Rule** statement, and (ideally) a real example of the failure it prevents
- Patterns should be domain-general (React, Python, Go — whatever). Project-specific patterns belong in the project's own `CLAUDE.md`, not in global patterns.

---

## Philosophy

Zaude has one thesis: **hooks for enforcement, skills for suggestions.**

When in doubt, put guarantees in hooks (the Claude Code harness enforces them) and advisory behavior in skills or pattern files (Claude follows them when relevant). Don't build features that try to enforce things via skill text alone — that's how we got the `/start` partial-read bug that started this whole project.

---

## Code of conduct

See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md). Short version: be direct, be kind, don't be a jerk.

---

## Questions?

Open a [discussion](https://github.com/ziadmomen10/zaude/discussions) — no PR needed. For bugs, file an [issue](https://github.com/ziadmomen10/zaude/issues) with reproduction steps.
