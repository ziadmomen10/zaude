# Changelog

All notable changes to Zaude are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Changed

#### `/decision-map` — recommendation-at-end + `go` adoption contract

- **Output restructured.** The **Recommendation** is now the final section of the report — after Context, Options, Analysis, draft entries for `open-questions.md` / `decisions.md`, and the "what I did NOT do" note. Rationale: the user's eye should land on the recommendation as the closing line, because that's where the action signal is. Section names and contents are unchanged; only position moved.
- **Breaking for position-dependent consumers.** If any downstream habit or script keyed on "Recommendation is the middle section of `/decision-map` output," it now appears last. No other structural changes.
- **Adoption signals — strict token match, mechanical.** The report now closes with an explicit invitation: `Reply `go` to start implementing Option X. Reply `go with <letter-or-name>` to adopt a different option, or redirect with a new constraint to re-analyze.` Signal recognition is deliberately narrow to avoid collisions with other Zaude workflow tokens:
  - **Bare adoption:** `go`, `yes`, `approved`, `implement it`. Must be the entire user reply (whitespace-trimmed, trailing punctuation stripped, case-insensitive).
  - **Named adoption:** `go with <X>` where X is a letter (A/B/C/…) or the full option name including `Defer`. Option-identifier match is case-insensitive. `adopt <X>` is deliberately NOT in the signal set — `go with <X>` is the single canonical named-adoption form.
  - **Rejection:** `no`, `reject`, `try again`, `revisit with <constraint>` → wait for new direction.
  - **Anything else, including hedged replies (`yes but option A`, `go check the README`):** wait. Explicitly NOT in the adoption set: `proceed`, `ship it`, `do it` — these collide with Zaude's destructive-action announcement closer (`Proceeding in one beat…`), the `/ship` command name, and ambiguous colloquial use.
- **Scope — turn-adjacent only.** Adoption signal fires ONLY when the user's reply is the very next user turn after the `/decision-map` emit. Any intervening user turn — clarifying question, other slash command, anything — closes the window. A later `go` is no longer adoption; Claude asks what it refers to.
- **Defer special case.** Adopting Defer means: acknowledge, print the revisit trigger (already in the report's Draft entry block), and do NOT write to disk. Per the file-writes prohibition, the user copies the Q&lt;N&gt; block manually.
- **Two-step authorization.** Adoption authorizes the work, not the ship. Implementation runs under `/build` semantics (`architect-review` DESIGN + `code-reviewer` + specialists per trigger rules). Commits still require `/ship` or an explicit `commit` request. A second `go` after implementation completes is NOT an adoption signal — scope window closed.
- **Composition rule added.** The `/decision-map → /build` handshake on adoption is documented in the skill's Composition section alongside the pre-existing `/build → /decision-map` suggestion (suggestion only, never auto-invoked).

### Added

#### CI — GitHub Actions 3-OS matrix

- **`.github/workflows/ci.yml`** (NEW) — syntax-checks matrix on `ubuntu-latest` + `macos-latest` + `windows-latest`. Covers Python stdlib compile on all hook `.py` files, bash parse on `install/install.sh` + `install/zaude-sync.sh` + `session-end-vault-sync.sh`, PowerShell parser on `install.ps1` (Windows leg only), and `json.load` validation across all tracked `.json` files. `concurrency` cancels superseded runs on the same ref. `fail-fast: false` so all OS legs run even if one fails.
- **CI badge in `README.md`** — first in the badge row, linked to the Actions tab. Signals live build status on the public repo.
- **Decision rationale:** adopted per `/decision-map` analysis of `open-questions.md` Q4 — minimal 3-OS matrix chosen over extended multi-Ubuntu variant because `ubuntu-latest` auto-tracks LTS at lower maintenance burden and the shell-compat risk surface (Git Bash/MSYS on Windows) is already covered by `windows-latest`. Resolves Q4; unblocks Q1 (public-flip).

#### `/e2e-test` — seventh slash command

- **`/e2e-test`** — production-readiness gate. Runs every applicable testing layer (types, lint, format, unit, integration, e2e, build, dep-audit, secret-scan, prod-checklist, plus opt-in a11y / perf / license on `--profile=deep`), computes increment-fit analysis against a git ref, dispatches 2 always-on + up to 3 conditional specialist agents, and produces a **SHIP / SHIP-WITH-CAUTION / HOLD** verdict. Manual-invocation only (5–45 min depending on profile). Never commits, never pushes, never modifies source files (carve-outs documented in Gates).
  - `templates/claude-config/commands/e2e-test.md` (NEW) — skill file with 8-phase workflow (Phase 0 preflight through Phase 8 emit), continue-on-fail semantics with `INCONCLUSIVE` layer status distinct from `SKIP`, three-profile axis (`quick` / `default` / `deep`), authoritative Profile × Layer matrix, and progress narration pattern for commands exceeding 5 min.
  - `docs/05-commands.md` — new section documenting phases, arguments, verdict thresholds, stack detection, artifacts, composition, with a realistic Node.js worked example demonstrating a SHIP-WITH-CAUTION verdict driven by missing integration tests.
- **Three verdicts** for `/e2e-test` — SHIP / SHIP-WITH-CAUTION / HOLD — severity-gated, not finding counts:
  - HOLD: any CRITICAL finding, unit/integration test failure, build failure, secret-scan finding in tracked files, HIGH+ dep-audit in **prod** dep, non-reversible forward migration (mechanical rule: additive DDL only, or explicit down-migration), or increment-fit breaking change without CHANGELOG diff / version-field bump / git-tag-on-HEAD acknowledgment.
  - SHIP-WITH-CAUTION: any HIGH finding, HIGH dev dep-audit, `e2e`/`integration` SKIP **scoped** to whether Phase 2 surfaced relevant changes (a project with no integration tests that changed only an internal utility is SHIP, not CAUTION), offline-forced skip, `--profile=quick` (automatic downgrade), coverage drop >5pp, or no tests at all.
  - SHIP: all clean, MEDIUM/LOW findings allowed.
- **Stack detection in v1: Node.js + Python + Go.** Detected by lockfile/config presence (monorepos run per-ecosystem with prefixed layer names). Rust/Ruby/Java/PHP/.NET deferred to v1.1+ with an optional `./.zaude/e2e-test.config.json` override path documented for custom stacks.
- **Agent dispatch matrix** — `architect-review` REVIEW mode + `code-reviewer` always-on; `security-auditor` / `test-automator` / `performance-engineer` conditional on specific signals. Typical run: 2 agents. Max: 5. Matches `/decision-map` conservatism when signal is absent. Security-auditor path-trigger globs narrowed to avoid false-firing on `tokenizer.ts` / design-token files.
- **Artifact directory** `.zaude/e2e-test/<ISO-timestamp>/` with `run.log`, `plan.json`, `findings.json`, `report.md`, `coverage/`, `junit/`, `playwright-trace/`. On first run, appends `.zaude/e2e-test/` to `.gitignore` (the only tracked-file write the command performs).
- **Five flags** for `/e2e-test` — `--profile` (quick/default/deep), `--scope` (CSV layer override; surgical, wins over profile), `--ref` (increment-fit anchor, defaults to merge-base with default branch via `git symbolic-ref`), `--offline` (auto-detected via HTTP HEAD probe to registry, handles corporate proxies), `--timeout` (per-phase seconds).
- **Progress narration pattern** — exactly one status line per phase boundary in format `[e2e-test Nm:Ss] Phase N/8 <slug> — <status>`. Canonical phase slugs table in skill file. Heartbeat before any command expected to exceed 5 min. No mid-phase narration, no sleep-and-poll, no incremental findings.

#### `/decision-map` — sixth slash command

- **`/decision-map <question>`** — structured analysis of stuck technical decisions. Read-only by design: never writes to `decisions.md`, never auto-appends to `open-questions.md`, never commits.
  - `templates/claude-config/commands/decision-map.md` (NEW) — skill file with 9-step workflow (Step 0 scope classifier → type classification with security-token override → vault precedent scan → option enumeration → specialist dispatch → scoring → anti-sycophancy self-check → confidence calibration → read-only emit).
  - `docs/05-commands.md` — new section with mermaid flow, gates, composition, and a worked example (rate-limiter decision re-litigation).
- **Anti-sycophancy primitives** — options presented alphabetically by assigned name (not user phrasing order); mandatory pre-emit self-check; refuses to invent filler options.
- **Specialist dispatch matrix** — `architect-review` DESIGN mode always + at most one conditional specialist (`security-auditor` / `performance-engineer` / `test-automator`) sequentially. Hard cap of two agents per invocation.
- **Five refusal outputs** — empty `$ARGUMENTS`, non-technical decision, already-settled without `--revisit` (or `--revisit` without detectable rationale), insufficient vault context (explicit `--force` flag required to override), every option fails hard-rule compliance.
- **Three flags** — `--revisit` (mechanical signal-word rationale check), `--force` (caps confidence at `low`), `--draft-decision` (print-only, never writes).

### Design decisions in this release

#### `/e2e-test`
- **Continue-on-fail, never halt-fast.** Downstream layers are marked `INCONCLUSIVE` (distinct from `SKIP`) when an upstream failure invalidates them, but the command runs every layer it can. Rationale: the user gets a full picture on every run, not the first-failure-only view.
- **Three-verdict model (not binary).** SHIP/HOLD was too blunt for a production-readiness gate. SHIP-WITH-CAUTION captures "the stack ran clean but coverage was incomplete" — scoped specifically to what the current increment actually touched, so a Node project with no integration tests is SHIP when the change didn't need integration coverage, SHIP-WITH-CAUTION when it did.
- **Secret scan covers tracked tree AND diff-since-ref.** A secret committed 6 commits ago and untouched today is still in the ship artifact. Scanning only the current diff would miss it.
- **`--ref` defaults to merge-base with default branch**, not "last tag." Tag-based anchors break on projects that haven't tagged recently or just cut one.
- **Mechanical checks all the way down.** Increment-fit breaking-change acknowledgment requires CHANGELOG diff / version-field change / git tag — not semantic inference. Migration reversibility is binary: additive DDL only, or explicit down-file. Security-auditor triggers on narrow glob patterns, not substring matches. Every judgment call was either mechanized or explicitly flagged as an open concern.
- **Agent count capped at 2 always-on + 3 conditional (5 max, 2 typical).** Earlier draft had 4 always-on. `architect-review` and `test-automator` overlap on "is the change coherent"; fire `test-automator` only when the test layer itself has signal.
- **Inline secret-scan pattern library in v1; external tools (trufflehog / gitleaks) in v1.1.** External tools would mandate a dependency; inline patterns are portable. Pattern library corrected during review to include AWS STS (`ASIA`), PKCS#8 private keys (no type prefix), and extended Slack token upper bounds.

#### `/decision-map`
- **Never writes to `decisions.md`.** That file is human-authored and append-only. If the command could write to it, precedent would contain AI-generated entries the user didn't actually decide — poisoning every future `/decision-map` run. Hard architectural guarantee, not a config option.
- **Sequential agent dispatch, not parallel.** Parallel `Skill`-dispatched agents produce interleaved output that's hard to attribute; 80% of decisions only need one specialist anyway. Parallel fan-out is deferred to v1.1 if real-world usage shows latency problems.
- **Dropped "strategic fit" as a scoring criterion.** Either it's objective hard-rule compliance (in the table) or it's taste (in a named "Taste / principles" recommendation line). Averaging the two produced hand-wavy scores that hid the judgment call.
- **Five load-bearing criteria, not eight.** Decision fatigue is the failure mode the command is designed to prevent — `/decision-map` cannot itself be a source of it. Situational criteria (user impact, maintenance burden, migration safety) appear only when they change the answer.
- **Confidence calibration is gated, not free-form.** `high` requires precedent-agrees AND unambiguous hard rules AND low-to-medium risk. Any skipped specialist caps confidence at `medium`. `--force` or thin `--revisit` rationale caps at `low`.
- **`/build` does NOT auto-invoke `/decision-map`.** Auto-invocation creates a workflow loop. Users reach for the command themselves; `workflow-orchestrator` may *suggest* it.

### Verified

#### `/e2e-test`
- Design spec produced by `architect-review` in DESIGN mode before implementation. Revisions to the draft incorporated: flag axis collapsed to single `--profile`, `--ref` default corrected to merge-base, three-verdict model, continue-on-fail semantics, Phase 0 preflight gate, execution-plan preview, stack-detection scope trimmed to v1 ecosystems (Node/Python/Go), secret-scan surface corrected to cover tree + diff-since-ref (not diff-only).
- Implementation reviewed by `code-reviewer` + `architect-review` REVIEW mode before commit. Findings addressed in-place across HIGH and MEDIUM severities: Profile × Layer matrix made authoritative (resolves `--profile=quick` layer-list ambiguity), secret-scan regexes hardened (Slack upper bound raised, PKCS#8 private keys covered, AWS STS `ASIA` included), security-auditor trigger globs narrowed to specific auth-context patterns, SHIP-WITH-CAUTION `e2e`/`integration` SKIP triggers scoped to Phase 2 relevance, increment-fit breaking-change check made mechanical, migration reversibility severity explicit (CRITICAL), network probe corrected to HTTP HEAD, package-manager precedence for multi-lockfile repos defined, tool-resolvability precheck added to Phase 1, debug-noise logger exclusion pattern-based, `.gitignore` carve-out from "NEVER modifies source" rule made explicit. Remaining LOW-severity polish items tracked separately.
- MVP scope discipline: Rust/Ruby/Java/PHP/.NET ecosystem detection, Lighthouse perf baseline trend storage, CI machine-readable output (JUnit/SARIF aggregation), rate-limit/CORS/security-headers prod-checklist items, testcontainers DB orchestration — all explicitly deferred to v1.1+ with rationale per item.

#### `/decision-map`
- Design reviewed in DESIGN mode by `architect-review` before implementation; raised concerns were incorporated or explicitly resolved before the skill file was written (scoring-criteria reduction from 8 → 5 load-bearing + 3 situational, sequential specialist dispatch vs parallel fan-out, dropped "strategic fit" as a scoring criterion, added Step 0 scope classifier, added mandatory anti-sycophancy pre-emit gate).
- Implementation reviewed by `code-reviewer` + `architect-review` REVIEW mode before commit; findings addressed in-place across CRITICAL, HIGH, and MEDIUM severities (alphabetical-ordering bug in worked example, mechanical `--revisit` rationale check, `--force` flag for insufficient-context opt-in, gate predicate corrections, docs/skill alignment on situational criteria and `/wrap` composition). Remaining LOW-severity polish items tracked separately.

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
