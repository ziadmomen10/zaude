# Changelog

All notable changes to Zaude are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

#### Agent expansion v0.5 — PR 1b (install automation + CI verification)

- **`install/install.sh` extended with v0.5 agent installer.** New `install_voltagent_v05()` function clones `VoltAgent/awesome-claude-code-subagents`, copies all 11 v0.5 specialists to `~/.claude/agents/`, and generates 10 `-readonly` variants via the portable awk pattern (accessibility-tester stays source-read-only). Interactive prompt at end of install flow: *"Install the 11 v0.5 VoltAgent specialists + their readonly variants now? [y/N]"* — default yes. Writes a `~/.claude/agents/.zaude-manifest` file tracking every Zaude-installed agent filename for clean uninstall (`rm $(grep -v '^#' .zaude-manifest | xargs -I{} echo ~/.claude/agents/{})`). Graceful degradation: if VoltAgent clone fails, skip with a warning and point user at the manual awk snippet in `docs/08-agents.md`.
- **`.github/ci/verify-agent-docs.py`** (NEW) — Python stdlib-only CI verification script. Hard-codes the canonical 11-agent v0.5 roster; verifies every agent name appears at least once in `templates/vault/03-patterns/agent-usage.md`, `docs/08-agents.md`, and `CHANGELOG.md`. Catches future doc drift where a new agent is added to the dispatch matrix but not the docs (or vice versa). Runs on all three OS legs of the existing CI matrix.
- **`.github/workflows/ci.yml` extended with "Agent docs parity" step** — runs the verification script after the JSON validation step. Non-zero exit fails the CI leg and surfaces exactly which agent is missing from which file.

**Not in this PR** (honestly deferred): PowerShell equivalent of the install-script extension. Windows users run the same install via Git Bash (already the documented + tested path for Zaude on Windows). A native PowerShell variant can land in a future polish PR if users report friction.

**Install is now one-shot.** Users cloning the repo + running `install.sh` get the full 29-agent Zaude roster (14 wshobson manually per docs + 11 VoltAgent v0.5 via the interactive prompt). The docs/08-agents.md manual awk snippets remain as documentation for users who want to install outside the script, or want to selectively install subsets.

### Fixed

#### v0.5.1 polish — LOW-backlog cleanup across seven files

- **Cross-doc "five commands" drift resolved** — `docs/01-introduction.md` (two places), `docs/02-installation.md`, `docs/03-architecture.md`, `docs/11-best-practices.md`, `install/setup-prompt.md`, and `templates/claude-config/CLAUDE.md` all now reference **eight commands** (adding `/decision-map`, `/e2e-test`, `/microscope` to the original five). CLAUDE.md's command table extended with three new rows. `CHANGELOG.md` v0.1.0 historical entry left untouched — it accurately reflects what shipped at the time.
- **`/e2e-test` "Pre-pipeline phases" section label fixed** — was incorrectly labeling Phase 7 (synthesis) and Phase 8 (emit) as "pre-pipeline." These are post-pipeline. Renamed the section header to "Always-on phases" (captures pre + post mandatory phases without implying ordering) and added a parenthetical clarifying the distinction.
- **`/e2e-test` debug-noise logger exclusion extended with underscore-separator patterns** — added `*_logger.*`, `*_logging.*`, `*_log.ts|js|py|go`. Go (`snake_case` by convention) and some Python projects use underscore-separated logger filenames (`application_logger.py`, `app_log.go`); the prior hyphen-only patterns missed these, producing false-positive MEDIUM findings on legitimate loggers. Backward-compatible — hyphen patterns still work.

### Added

#### Agent expansion v0.5 — PR 4 (Tier 3 opt-in: mcp-developer) — v0.5 agent roster complete

- **Final v0.5 specialist ships: `mcp-developer` (`mcp-developer-readonly`).** Build/debug/optimize MCP servers and clients. Fires on `.claude/mcp*.json` / `@modelcontextprotocol/sdk` in deps / `mcp` package in `pyproject` / MCP tool definitions. Tier 3 opt-in — zero overhead if not triggered.
- **v0.5 target reached: 29 agents installable** (18 core + 11 VoltAgent specialists). All dispatch triggers live in `agent-usage.md` from PR 1a. Skill files reference the single source of truth; no inline dispatch rules.
- **`docs/08-agents.md` install block is now complete** — one loop copies all 11 v0.5 specialists. Variant-generator awk loop covers the 10 write-capable (accessibility-tester still excluded with inline comment).
- **`agent-usage.md` rollout-status line** reflects completion: v0.5 roster live; PR 1b (install-script automation) still pending.
- **`README.md` updated** — agent orchestration row rewritten to enumerate all 29 agents with clear core-vs-specialist split; v0.5 rollout-phase language dropped now that the series is complete.

Remaining from the v0.5 series: PR 1b (install.sh + install.ps1 automation + .zaude-manifest format + CI verify-agent-manifest script). User-facing install today uses the portable awk loops documented in `docs/08-agents.md` — functionally complete, just not automated.

#### Agent expansion v0.5 — PR 3 (Tier 2 — 4 specialists)

- **Roster expansion from 24 → 28 agents.** Four Tier 2 VoltAgent specialists ship in this PR: `react-specialist`, `docker-expert`, `documentation-engineer`, `accessibility-tester`. Each already had dispatch triggers in `agent-usage.md` from PR 1a — install-side only.
- **`react-specialist` (`react-specialist-readonly`)** — React 18+ deep specialist (concurrent features, state-library selection, perf optimization, advanced patterns). Fires on `*.tsx`/`*.jsx` diffs with React-specific signals (`useMemo`/`useCallback`/`useTransition`/`useDeferredValue`/`Suspense`, or state-management-strategy changes). Runs sequentially after `frontend-developer` — FE-dev designs component shape; react-specialist tunes React-specific parts.
- **`docker-expert` (`docker-expert-readonly`)** — Docker image build/optimize/secure (multi-stage, BuildKit, scanning, SBOM). Fires on `Dockerfile` / `docker-compose*.yml` / `.dockerignore` diffs. Parallel with `deployment-engineer` on PRs touching both Dockerfile + CI workflow.
- **`documentation-engineer` (`documentation-engineer-readonly`)** — documentation-system architect (API docs, tutorials, static-site generators). Fires on >50% docs diffs or static-site generator config. Notable limitation: `haiku` model with no `Bash` tool (architecture + content, not build pipeline).
- **`accessibility-tester`** — WCAG 2.1/3.0 compliance testing, ARIA verification, keyboard nav, color contrast. **Ships with source-level read-only tool surface** (no `-readonly` variant needed — Zaude's triggers reference the base name). Always-on at `/e2e-test --profile=deep`, closing the prior "a11y layer skipped in v1" gap.
- **`docs/08-agents.md` install block extended** — now copies all 10 Tier 1 + Tier 2 agents. Variant-generator awk loop covers all 9 write-capable ones; `accessibility-tester` explicitly excluded with a comment.
- **`agent-usage.md` rollout-status line updated** — reflects Tier 1 + Tier 2 complete (10 agents); PR 4 `mcp-developer` opt-in pending.
- **`README.md` count updated** — `24 → 28`; Tier 2 specialists listed by name.

#### Agent expansion v0.5 — PR 2 (Tier 1 rest — 4 specialists)

- **Roster expansion from 20 → 24 agents.** Four additional VoltAgent specialists ship in this PR: `sql-pro`, `python-pro`, `prompt-engineer`, `refactoring-specialist`. Each already had its dispatch trigger rule in `agent-usage.md` (shipped in PR 1), so PR 2 is install-side only — no skill file changes.
- **`sql-pro` (`sql-pro-readonly`)** — cross-RDBMS expert for CTEs, window functions, ANSI-standard patterns. Fires on raw `.sql` / stored procedure / view DDL when target isn't exclusively Postgres. Suppressed when `postgres-pro` is already firing (postgres-pro wins on Postgres-only work per the hard-overlap precedence rule).
- **`python-pro` (`python-pro-readonly`)** — modern Python 3.11+ (type hints, async, Pydantic, pytest). Fires on `*.py` diffs above 20 lines OR touching async/type-annotation/Pydantic/FastAPI/Django/pytest-fixture surfaces. Notable meta-effect: **reviews every Zaude hook edit** via `/ship` and `/wrap` since all Zaude hooks are stdlib Python.
- **`prompt-engineer` (`prompt-engineer-readonly`)** — LLM prompt design/optimization/evaluation. Fires on prompt-template files, system-prompt strings, LLM API call prompts >5 lines, `prompts/` or `templates/` dirs, or agent `*.md` with system-prompt body changes. Notable meta-effect: **fires on every Zaude skill-file / agent-file edit**, providing prompt-quality review on Zaude's own authoring surface.
- **`refactoring-specialist` (`refactoring-specialist-readonly`)** — behavior-preserving code restructure planning. Fires on `/build` with keywords `refactor` / `restructure` / `clean up` / `extract` / `rename` / `deduplicate` / `simplify`. The behavior-preservation check is now the agent's own responsibility, not a dispatch condition (tightened from PR 1 per review findings). Wired into `/decision-map` Step 4 `refactor` class (shipped in PR 1, now backed by a real installed agent).
- **`docs/08-agents.md` install block extended** — the install loop now includes all 6 Tier 1 agents. The variant-generation awk loop also extended to produce `-readonly` variants for all 6. The remaining 5 (Tier 2 + 3) are still documented for forward reference but deferred to PRs 3-4.
- **`agent-usage.md` rollout-status line updated** — reflects PR 2 completing Tier 1 (6 agents live); PR 3 and PR 4 remain for Tier 2 (4 agents) and Tier 3 (1 agent opt-in).
- **`README.md` count updated** — `20 → 24` agents as of PR 2; full roster of Tier 1 specialists listed by name.

#### Agent expansion v0.5 — PR 1 (infrastructure + 2 pilot specialists)

- **Roster expansion from 18 → 20 agents** (pilot of a planned 18 → 29 across four PRs). Two new VoltAgent specialists shipped in this PR: `debugger` and `postgres-pro`. Remaining 9 ship in PRs 2–4 (4 tier-1, 4 tier-2, 1 tier-3-opt-in).
- **`debugger` (`debugger-readonly` for read-only commands)** — diagnose bugs, identify root causes, analyze logs / stack traces. **Closes the flagged gap in `/microscope`**: Phase 4 synthesis now dispatches `code-reviewer` + `debugger-readonly` as always-on pair (was `code-reviewer` alone). Dispatch cap raised from 3 to 5 to accommodate. Prior "no dedicated debugger agent in the roster" caveat removed.
- **`postgres-pro` (`postgres-pro-readonly` for read-only commands)** — PostgreSQL-ONLY specialist for vacuum, WAL, replication, JSONB, GIN/BRIN, partitioning. Fires on diffs touching `*.sql` / `**/migrations/**` / `postgresql.conf` / Postgres-specific identifiers. Wired into `/build`, `/review`, `/ship`, `/decision-map` (class=data), `/e2e-test` (Phase 4), `/microscope` (Phase 4 conditional).
- **`agent-usage.md` is now the single source of truth** for agent dispatch. New sections: "Mechanical triggers (v0.5+ VoltAgent specialists)" with 11 mechanical trigger rows, "Hard-overlap precedence" with 10 resolution rules for agent-pair conflicts, "Agent dispatch cap" with the 5-agent hard rule and precedence ladder (language-specialist > framework-specialist > generalist > reviewer). Loaded by `SessionStart` into every session.
- **Skill files reference `agent-usage.md`** rather than duplicating dispatch rules. `build.md`, `review.md`, `ship.md`, `wrap.md`, `decision-map.md`, `e2e-test.md`, `microscope.md` each add a short section pointing to `agent-usage.md` as authoritative. No inline rule duplication.
- **Read-only variant discipline documented.** Write-capable agents (9 of the 11 new specialists) ship `-readonly` variants that strip `Write`/`Edit` from their `tools:` frontmatter and prepend a Zaude-injected preamble ("Zaude read-only mode. Do NOT attempt to write or edit files…"). Read-only commands (`/microscope`, `/e2e-test`, `/decision-map`, review chains) invoke the `-readonly` variant by name. `docs/08-agents.md` now includes the variant-generation bash snippet; an automated install script follows in PR 1b.
- **`docs/08-agents.md` refreshed** — 29-agent count throughout; new VoltAgent specialists table with 11 rows (role, primary trigger, readonly-variant-yes/no); explicit install commands for the 2 pilot agents in this PR; new "Generate read-only variants" section with the sed-based pattern.
- **`/microscope` Phase 4 matrix extended** — `debugger-readonly` always-on, plus conditional `postgres-pro-readonly`, `python-pro-readonly`, `react-specialist-readonly` rows. Documentation updated so future readers see `debugger` as the closed-gap specialist, not a missing roster slot.
- **`/decision-map` Step 4 matrix extended** — `data` classification now dispatches `postgres-pro-readonly` (Postgres-specific work) with fallback to `security-auditor` if PII/auth/credentials involved and not Postgres. `refactor` classification now dispatches `refactoring-specialist-readonly` (the specialist for behavior-preserving restructure planning) instead of `test-automator`. `dependency` classification adds `docker-expert-readonly` conditional.
- **`/e2e-test` Phase 4 matrix extended** — `postgres-pro-readonly`, `docker-expert-readonly`, and `accessibility-tester` added as conditional rows. `accessibility-tester` is the new always-on agent at `--profile=deep`, replacing the prior "a11y layer skipped in v1" gap.

### Design decisions in this release

#### Agent expansion v0.5 PR 1
- **Single source of truth for dispatch.** All mechanical triggers live in `templates/vault/03-patterns/agent-usage.md`. Skill files reference it; they never duplicate. SessionStart already loads the pattern file — no hook change needed.
- **Read-only variants are deterministic, not judgment-based.** Write-capable agents invoked in read-only contexts would otherwise be "trust the model to not mutate" — which is judgment. A stripped-tools variant is mechanically enforced by the sandbox.
- **Mechanical triggers only — no "Claude decides."** Every new dispatch rule is file-path glob, content regex, command-argument match, or prior classification. Anti-sycophancy discipline carried forward from `/decision-map`.
- **Additive for new agents; two retargets in `/decision-map` Step 4.** Every new agent's dispatch rule is purely additive. Two existing `/decision-map` Step 4 class dispatches were retargeted to the new specialists: `data` class now uses `postgres-pro-readonly` (with `security-auditor` retained as fallback for PII/auth/credentials signals on non-Postgres stacks), `refactor` class now uses `refactoring-specialist-readonly` (replaces `test-automator`, which was a loose fit — refactoring-specialist is the purpose-built agent for behavior-preserving restructure planning). No other command contracts change; rollback is `git revert` + removing two agent files from `~/.claude/agents/`.
- **Hard-overlap precedence is explicit, not negotiated.** 10 resolution rules for the pairs that could contradict (e.g., `postgres-pro` vs `backend-developer`, `react-specialist` vs `frontend-developer`). Each rule names the winner by signal and the both-fire condition when applicable.
- **5-agent dispatch cap.** When trigger rules would fire more than 5 agents on a single turn, the precedence ladder suppresses lower-tier agents and the command's output flags the suppression ("Dispatch cap reached; X suppressed").

### Verified

#### Agent expansion v0.5 PR 1
- Research spec produced via a dedicated agent that fetched all 13 source files (11 new VoltAgent agents + 2 existing VoltAgent agents for overlap baseline). No 404s. Every dispatch rule in `agent-usage.md` grounded in the actual source file's declared `tools:` frontmatter and body workflow.
- Architectural plan delivered as v1 document with per-agent cards, tool-surface normalization rules, dispatch matrix, install specification, verification specification, rollback specification, failure-mode catalog, and phased rollout gates. Approved by user before implementation.
- Implementation reviewed by `code-reviewer` + `architect-review` REVIEW mode before commit. Findings addressed in-place.

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

#### `/microscope` — eighth slash command

- **`/microscope`** — live-audit a test run. Pre-loads the test file + function-under-test (depth-1 imports, capped at 15 files or 3,000 lines) + fixtures + recent git diff BEFORE execution, then streams runner events in real time via `Bash run_in_background=true` + `Monitor`, falling back to synchronous+buffered mode when streaming is unavailable (flagged as `Streaming mode: degraded-buffered`). Emits a ranked root-cause hypothesis list with mechanical grading: HIGH = event↔context link + (diff corroboration OR structural bug visible); MEDIUM = event link alone; LOW = reasoned guess. Each hypothesis cites file:line + code snippet, streamed event timestamp, fix sketch (prose, not diff), verification command.
  - `templates/claude-config/commands/microscope.md` (NEW) — 6-phase skill file (preflight → context-load → instrumentation-plan → live-execution → synthesis → emit). Recognized runners in v1: vitest, jest, mocha, pytest, go test, playwright, cypress — each with a concrete regex row for event classification. Unrecognized runners fall back to `raw` mode with reduced narration.
  - `docs/05-commands.md` — new section documenting phases, arguments, streaming contract, hypothesis grading, composition, artifacts. Worked example demonstrates HIGH hypothesis with diff corroboration.
- **Narration rate-limit.** One annotation per event class per event (runner-start / test-start / test-result / assertion-fail / error / hook). Everything else silently collapsed into `run.log` + `events.jsonl`. Prevents noisy test suites from blowing the token budget.
- **Agent dispatch for `/microscope`.** `code-reviewer` always-on (unless `--no-agents`); `security-auditor` conditional on auth-context path match (reuses `/e2e-test`'s narrowed glob list); `architect-review` REVIEW mode conditional on cross-module hypothesis (≥2 modules cited as bug location). Max 3 agents. Typical run: 1.
- **Six flags for `/microscope`** — `--test` (passed verbatim), `--focus` (narrow context), `--layers` (runner/code/types/logs in v1), `--timeout` (per-phase seconds), `--rerun` (v1 honors 1 only; flake detection v1.1), `--no-agents` (skip Phase 4 for fast iteration).
- **Artifact directory** `.zaude/microscope/<ISO-timestamp>/` parallel to `/e2e-test`: `run.log`, `plan.json`, `hypotheses.json`, `report.md`, `events.jsonl` (JSONL of every streamed event with classification), `context/` subdir snapshotting every file loaded in Phase 1 for post-hoc reproducibility.
- **Copy-paste suggestion in `/e2e-test` HOLD output.** When `/e2e-test` returns HOLD with a specific layer failure, the Recommendation section now includes `Drill further: /microscope --test="<failing-layer-command>"`. Suggestion only, not auto-invocation — `/microscope` remains strictly manual. This is the single documented cross-command integration between the two test-time commands.
- **`JUDGMENT CALL:` markers** used in `/microscope` skill file at two points where judgment is unavoidable (tied hypothesis ranking, ambiguous event classification). Mechanical rules get no marker; judgment calls get flagged explicitly so Claude reading the skill knows where the spec stops and interpretation begins. Pattern adoptable by other commands.

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

#### `/microscope`
- **Live audit, not post-mortem.** `/microscope` attaches to a running test and narrates events as they stream; it is not a log parser. When streaming is unavailable, it degrades to buffered-annotation mode rather than refusing — the core value (context + hypothesis grounded in evidence) survives the downgrade. Explicitly flagged in the output header so users know which mode ran.
- **v1 layers trimmed to `runner` + `code` + `types` + `logs`.** HTTP / DB / FS are v1.1+. HTTP requires per-framework hooks (Playwright's `page.on('response')` works; vitest/pytest don't have native equivalents). DB requires ORM-specific log wrappers (Prisma / SQLAlchemy / GORM — no universal pattern). FS requires OS-level tracing (strace / dtrace / ProcMon) — non-portable. v1 scope is what every runner reliably emits.
- **Hard cap on Phase 1 context load.** 15 files / 3,000 lines at depth-1 imports. Prevents the "follow the import graph forever" token bomb. Cap-hit is flagged in output with `--focus` as the documented escape hatch.
- **Hypothesis grading is mechanical.** HIGH requires direct event↔context evidence link AND (diff corroboration OR visible structural bug). No judgment-promoted hypotheses. Each hypothesis must cite code Claude actually loaded in Phase 1 — unloaded-code hypotheses emit as `unexplored — re-invoke with --focus`.
- **No fix application, no test re-run.** The command is strictly a diagnostic; the user authors every fix and drives every iteration. Adoption-contract-style `go` signal for auto-applying fixes is NOT wired — hypothesis section is print-only like `/decision-map`'s draft entries.

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

#### `/microscope`
- Design spec produced by `architect-review` in DESIGN mode before implementation. Substantive revisions to the draft incorporated: per-event-class rate-limit matrix replacing per-assertion streaming fantasy; mechanical scrollback invocation rule (most recent bash with non-zero exit + recognized runner pattern) replacing judgment-based detection; v1 layers trimmed to runner/code/types/logs (dropped HTTP/DB/FS to v1.1+); Phase 1 context load hard-capped at 15 files / 3,000 lines; degraded-buffered fallback when streaming unavailable (not a refusal); hypothesis grading made mechanical (event↔context link required for HIGH); agent dispatch capped at 3 (code-reviewer always + 2 conditional); `JUDGMENT CALL:` markers used at the two points where judgment is unavoidable (tied ranking, ambiguous event classification).
- Implementation reviewed by `code-reviewer` + `architect-review` REVIEW mode before commit. Findings addressed in-place across HIGH and MEDIUM severities.
- MVP scope discipline: HTTP/DB/FS layers, flake detection via `--rerun=N`, project-level `./.zaude/microscope.config.json` override for custom runners, `/e2e-test --drill-on-fail=<layer>` opt-in auto-invocation, dedicated `debugger` agent — all explicitly deferred to v1.1+ with rationale per item.

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
