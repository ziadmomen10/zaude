# Changelog

All notable changes to Zaude are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

---

## [0.2.0] — 2026-04-17

### Added
- **Trademark protection:**
  - `TRADEMARK.md` — full trademark policy (permitted / restricted / prohibited uses, fork-rename requirements, enforcement, contact). Modeled on Rust / Python / Linux / Kubernetes.
  - `NOTICE` — mandatory attribution under MIT.
  - `LICENSE` preamble clarifying Zaude™ is an unregistered trademark separate from the MIT code license.
  - `README` trademark badge + expanded license/trademark section + forks-must-rename clause.
  - `CONTRIBUTING.md` contributor agreement (CLA-lite: opening a PR grants MIT to code; trademark stays with Ziad Momen).
- **Auto-sync machinery (PR-only, never direct to main):**
  - `install/zaude-sync.sh` — 8-phase sync pipeline: stage → diff against `origin/main` → genericization lint on added lines → branch → commit → push → open PR via `gh`. Supports `--dry-run`, `--lint-only`, `--yes` modes.
  - `templates/claude-config/commands/zaude-push.md` — new `/zaude-push` slash command with Claude-supervised lint → preview → confirm → push flow.
  - Extended `templates/claude-config/hooks/session-end-vault-sync.sh` with `auto_sync` config flag. When true, fires `zaude-sync.sh --yes` automatically when a session's auto-commit touches a framework file. Still PR-only.
  - New config fields in `config.sample.json`: `zaude_repo_path`, `auto_sync`, `sync_private_markers`, `sync_exclude`.
- **`docs/14-auto-sync.md`** — full architecture walkthrough, genericization lint semantics, three ways to run it, worked examples for both clean and lint-failure cases, safety properties, disabling procedure.

### Fixed
- `config.sample.json` was unintentionally excluded from git tracking by the nested `templates/claude-config/.gitignore` — added to allowlist (`2d453f3`).
- Python on Windows can't open Git Bash `/c/...` paths. Normalized via `cygpath -m` before Python invocation in `zaude-sync.sh` and `session-end-vault-sync.sh` (`9942d17`).
- Python `print()` on MSYS pipes adds `\r\n` — strip trailing `\r` when populating `SYNC_EXCLUDE` array so substring match works (`9942d17`).
- Shell-quote escaping in Python heredocs replaced with environment-variable passing for config path + field (`9942d17`).

### Design decisions in this release
- Auto-sync is PR-only forever. Direct push to `main` is rejected at the architecture level, not as a config option.
- Genericization lint runs on the ADDED lines of the diff, not the full file — legitimate marker-shaped content already on `main` doesn't block future syncs.
- The trademark is unregistered (common-law) for now. USPTO registration deferred until adoption warrants it.

---

## [0.1.0] — 2026-04-17

Initial public release.

### Added
- Five slash commands: `/start`, `/build`, `/review`, `/ship`, `/wrap`
- Three Claude Code hooks:
  - `SessionStart` — mechanical vault loader, reads project + patterns + memory as `additionalContext`
  - `PreToolUse` — frozen-zone guard blocking writes to configured paths
  - `SessionEnd` — auto-commit and push for both vault and Claude-config repos
- Vault pattern:
  - `VAULT_PROTOCOL.md` top-level protocol
  - `01-projects/<slug>/` skeleton (CLAUDE.md, current-state.md, decisions.md, open-questions.md, spec.md, architecture.md, sessions/)
  - `03-patterns/` with anti-patterns, credential-handling, agent-usage
- Global `CLAUDE.md` template
- `settings.json` template wiring all three hooks
- `config.sample.json` schema with documented fields
- Install scripts (`install.sh` for macOS/Linux/WSL, `install.ps1` for Windows)
- Interactive setup prompt at `install/setup-prompt.md`
- Example project demonstrating the vault layout
- Full documentation set (13 chapters) under `docs/`
- Logo SVG, banner SVG, Mermaid diagram sources

### Design decisions in this release
- Hooks for enforcement, skills for suggestions (see `03-patterns/anti-patterns.md` rule 1)
- Decision log is append-only; no rotation or archiving
- Memory files are cwd-keyed and tracked in the Claude-config repo
- Two separate repos (vault + claude-config) rather than one merged repo — separates project knowledge from user-level tooling
