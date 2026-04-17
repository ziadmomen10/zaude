# Changelog

All notable changes to Zaude are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

---

## [0.3.0] — 2026-04-17

### Added
- **Status-freshness enforcement** — prevents Claude from anchoring to stale prose in `current-state.md` at session start (the canonical "12/14 vs 15/15" class of disaster). Three pieces working together:
  - `templates/claude-config/hooks/lib/freshness_parse.py` (NEW) — single source of truth for `BLOCK_RE`, `BLOCK_RE_SPLICE`, YAML parser (PyYAML + handwritten fallback), `sanitize_for_injection`, `read_capped`, required-field schema. All three hooks import from it — no regex drift possible.
  - `templates/claude-config/hooks/current-state-freshness.py` (NEW) — SessionEnd observer + `--check` mode. Validates the `<!-- status-freshness -->` block has today's date, points to the latest session log, has required fields. Respects `FRESHNESS_ENFORCE` env var (case-insensitive: `1`/`true`/`TRUE`/`YES`). Path-traversal guard via `realpath` + `commonpath`. Warn-only contradiction detection on body-text `N/N noun` patterns.
  - `templates/claude-config/hooks/lib/regen-freshness.py` (NEW) — `/wrap` helper. Parses today's `sessions/YYYY-MM-DD.md` for verified claims via 4 pattern classes (checked items, ratios, verified markers, confidence words) with consumed-span dedup + `MAX_SCENARIOS=5` cap. Atomic write via `tempfile.mkstemp` + `os.replace`. ISO-date validation on `--log` argument prevents path traversal. Lambda replacement in `BLOCK_RE_SPLICE.sub` so claim text containing `\1` / `\g<name>` doesn't explode as regex backref.
- **Extended `session-start-vault.py`** — prepends `=== VERIFIED FACTS ===` (happy path) or `=== FRESHNESS WARNING ===` (stale/missing) to `additionalContext` above the existing vault dump. Every claim/name/source/date passes through `sanitize_for_injection` first, neutralizing `===` / `<!--` / `-->` / control chars / overlong strings — prevents prompt injection under `--dangerously-skip-permissions`. 1 MB per-file cap on all vault reads.
- **`/wrap` step 8 + 9** — step 8 runs `regen-freshness.py`, step 9 runs `FRESHNESS_ENFORCE=1 python ~/.claude/hooks/current-state-freshness.py --check` as the real gate. The SessionEnd hook entry is observability-only; `/wrap` is where enforcement lives.
- **Settings.json template** — `current-state-freshness.py` wired into `SessionEnd` before `session-end-vault-sync.sh` for clear intent (ordering is cosmetic since SessionEnd can't gate, but makes the flow readable).

### Design decisions in this release
- **SessionEnd hooks cannot block anything.** Per the official Claude Code docs, SessionEnd exit codes print stderr to the user but do not halt session termination and do not gate other hooks. The enforcement point is `/wrap` step 9 where Claude is still engaged and can respond to a validation error by re-running regen. SessionStart injection is the runtime safety net for any session that bypassed `/wrap`.
- **One regex, three hooks.** Declaring `BLOCK_RE` three times across three files would guarantee future drift. `lib/freshness_parse.py` is the single source; three hooks import. Trivial `sys.path` overhead, eliminates a whole class of silent-format-skew bugs.
- **Sanitizer sentinels don't contain their inputs as substrings.** `===` → `[=x=]`, `<!--` → `[!--`, `-->` → `--]`. A naive `-->` → `[-->]` would leak the literal `-->` as a substring; explicit check in tests.
- **Contradiction detection is warn-only.** If body text says `15/15 steps` but the block doesn't mention it, emit a warning; don't block. Blocking on contradictions would make legitimate narrative drift painful; the block is the source of truth, the body is commentary.

### Verified
- Two rounds of formal review (`code-reviewer` + `security-auditor` + `architect-review`) in parallel: 2 CRITICAL + 8 HIGH found and fixed in round 1; 3 new HIGH found and fixed in round 2.
- 169-test E2E harness across 19 categories (parser, validator, regen, injector, frozen-guard, settings wiring, Zaude parity, auto-sync, memory system, MCP config, vault structure, docs, install files, `/wrap` pipeline simulation, orchestration chain order): **168/169 pass**. The one failure was a pre-existing framework state (agent file missing YAML frontmatter), not a regression from this feature.

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
