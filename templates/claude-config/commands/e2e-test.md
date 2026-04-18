Run a production-readiness gate on the current state: every testing layer the project supports, plus increment-fit analysis, prod checklist, and specialist review. Slow (5–45 min depending on `--profile`), manual-invocation only, read-only — never commits, never pushes, never modifies source files.

## When to use this

Before shipping a high-stakes increment. Not for every commit — `/review` handles fast pre-commit checks. `/e2e-test` answers "if we deployed this exact state to production right now, would it survive?" and answers it with real test execution, not just review heuristics.

Do NOT run this as part of `/ship` or `/wrap`. It is opt-in for the user who wants the heavier gate.

## Arguments

```
/e2e-test [--profile=quick|default|deep]
          [--scope=<csv>]
          [--ref=<git-ref>]
          [--offline]
          [--timeout=<seconds>]
```

| Flag | Default | Semantics |
|---|---|---|
| `--profile` | `default` | Target durations: `quick` <3 min; `default` 5–15 min; `deep` 15–45 min. Exact layer membership is in the **Profile × Layer matrix** below — this table is authoritative, not the prose. |
| `--scope` | auto from `--profile` | Comma-separated explicit layer list: `types,lint,format,unit,integration,e2e,build,dep-audit,secret-scan,prod-checklist,a11y,perf,license`. Overrides the profile's layer set. Listed layers run; unlisted skip with reason `skipped by --scope`. |
| `--ref` | merge-base with default branch | Git ref to compare increment against. Default resolves via `git symbolic-ref refs/remotes/origin/HEAD` → fallback `main` → fallback `master` → preflight refusal if none resolve. |
| `--offline` | auto-detected | Skip network-dependent layers (dep-audit, license audit). Auto-set if the Phase 1 network probe fails (3s timeout, HTTP HEAD against a well-known registry). |
| `--timeout` | `600` | Per-phase timeout in seconds. A phase exceeding this is killed; layer status becomes `TIMEOUT`. Does not cancel downstream phases. |

### Profile × Layer matrix (authoritative)

Pre-pipeline phases (Phase 0 preflight, Phase 1 stack-detect, Phase 2 increment-fit, Phase 7 synthesis, Phase 8 emit) **always run** regardless of profile — `quick` is not "skip synthesis", it's "skip expensive layers." The two always-on agents in Phase 7 (`architect-review` + `code-reviewer`) fire on every run.

| Layer | `quick` | `default` | `deep` |
|---|---|---|---|
| types | ✅ | ✅ | ✅ |
| lint | ✅ | ✅ | ✅ |
| format | ✅ | ✅ | ✅ |
| unit | ✅ | ✅ | ✅ |
| secret-scan | ✅ | ✅ | ✅ |
| prod-checklist | ✅ | ✅ | ✅ |
| integration | ❌ | ✅ | ✅ |
| e2e | ❌ | ✅ | ✅ |
| build | ❌ | ✅ | ✅ |
| dep-audit | ❌ | ✅ | ✅ |
| a11y | ❌ | ❌ | ✅ |
| perf (Lighthouse) | ❌ | ❌ | ✅ |
| license | ❌ | ❌ | ✅ |

`--scope=<csv>` is the surgical override — it replaces whatever the profile selected with the explicit list. A layer disabled by profile AND enabled by `--scope` runs (scope wins). A layer enabled by profile AND omitted from `--scope` skips with reason `skipped by --scope`.

## Phases

Eight phases. Each phase declares execution mode (sequential | parallel) and halt behavior. **No phase cancels downstream phases** — every phase runs to completion; downstream layers that depended on a failed upstream layer are marked `INCONCLUSIVE` (distinct from `SKIP`). The user gets a full picture on every run, not first-failure-only.

**Canonical phase names** (used verbatim in progress narration — no variation):

| Phase | Slug |
|---|---|
| 0 | `preflight` |
| 1 | `stack-detect` |
| 2 | `increment-fit` |
| 3 | `fast-checks` |
| 4 | `integration` |
| 5 | `e2e-heavy` |
| 6 | `prod-checklist` |
| 7 | `synthesis` |
| 8 | `emit` |

**Behaviors outside the preflight gate** — uncommitted-changes handling, `NOTHING-TO-TEST` advisory, re-invocation artifact handling — are documented in the **Gates** section below, not duplicated per-phase.

### Phase 0 — Preflight (sequential, fail-fast)

Hard prerequisites. If any check fails, emit a **preflight error** and exit. A preflight error is NOT a verdict — it means the command could not run.

Checks, in order:

1. `.git/` exists in the repo root. If not → refuse: "Zaude's `/e2e-test` requires git for increment-fit analysis."
2. `--ref` resolves to a valid SHA. If not → refuse with the `git rev-parse --verify` stderr.
3. Stack detection (Phase 1 preview): at least one supported ecosystem is detected. Supported in v1: **Node.js, Python, Go**. If none detected and source files are present → refuse: "No supported ecosystem detected. v1 supports Node / Python / Go. For other stacks, declare per-layer overrides via `./.zaude/e2e-test.config.json` (schema documented in Phase 1) or run per-ecosystem commands manually."
4. Free disk space ≥500 MB. If not → refuse: "Tests risk spurious failures on low disk; free up space."
5. Currently on a detached HEAD with no `--ref` provided → refuse: "Detached HEAD has no default anchor. Re-invoke with `--ref=<sha-or-ref>`."

If all preflight checks pass, emit the opening status line and proceed:

```
[e2e-test 0m:00s] Phase 0/8 preflight — done (git OK, ref OK, stack OK, disk OK)
```

### Phase 1 — Stack detection and execution plan (sequential)

Deterministic scan of the repo root. Produces the **execution plan**: for every applicable layer, a record of `{ status: "will run" | "skip: <reason>", command, cwd, timeout }`.

Detection algorithm (apply in order; a project may match multiple ecosystems — run all detected):

#### Project-level override

Check for `./.zaude/e2e-test.config.json`. If present, merge over defaults. Config schema:

```json
{
  "layers": {
    "<layer-name>": {
      "enabled": true,
      "command": "npm run test:custom",
      "cwd": "./apps/api",
      "timeout": 900
    }
  }
}
```

Overrides never silently disable layers — they appear in the plan output with reason `config override`.

#### Ecosystem detection (scan root, depth 1)

| Ecosystem | Trigger files |
|---|---|
| Node.js | `package.json` |
| Python | `pyproject.toml`, `requirements.txt`, `Pipfile`, `setup.py` |
| Go | `go.mod` |

If multiple match (monorepo): detect all, run per-ecosystem, prefix layer names with ecosystem in the report (`node/types`, `python/lint`).

#### Per-ecosystem, per-layer detection

For each detected ecosystem, identify configured layers by config-file presence. For each layer, prefer user-declared scripts (`package.json` `scripts`, `pyproject.toml` `[tool.*]`) over canonical invocations.

| Layer | Node triggers | Python triggers | Go triggers |
|---|---|---|---|
| types | `tsconfig.json` → `tsc --noEmit` | `mypy.ini`, `pyrightconfig.json`, `pyproject.toml[tool.mypy]` → `mypy .` or `pyright` | built-in via `go build ./...` |
| lint | `.eslintrc.*`, `eslint.config.*` → `eslint .` | `ruff.toml`, `.ruff.toml`, `pyproject.toml[tool.ruff]`, `.flake8` → `ruff check .` or `flake8` | `.golangci.yml` → `golangci-lint run` |
| format | `.prettierrc.*`, `prettier.config.*` → `prettier --check .` | `pyproject.toml[tool.black]` → `black --check .` | built-in → `gofmt -l .` (non-empty output = fail) |
| unit | `vitest.config.*` → `vitest run`; `jest.config.*` → `jest`; `.mocharc.*` → `mocha` | `pytest.ini`, `pyproject.toml[tool.pytest]`, `conftest.py` → `pytest` | `*_test.go` → `go test ./...` |
| integration | `tests/integration/**`, `**/*.integration.test.*` | `tests/integration/`, pytest markers `@pytest.mark.integration` | `*_integration_test.go` |
| e2e | `playwright.config.*` → `playwright test`; `cypress.config.*` → `cypress run` | rarely applicable | rarely applicable |
| build | `package.json[scripts.build]` → `<pm> run build` | `setup.py` / `pyproject.toml[project]` → `python -m build` (if configured) | `go build ./...` |
| dep-audit | `<pm> audit --omit=dev` (npm/pnpm/yarn/bun, with package manager detected from lockfile) | `pip-audit` if installed, fallback `safety check` | `govulncheck ./...` if installed |
| secret-scan | always applicable | always applicable | always applicable |

#### Package manager detection (Node only)

| Lockfile | Manager |
|---|---|
| `bun.lockb` | `bun` |
| `pnpm-lock.yaml` | `pnpm` |
| `yarn.lock` | `yarn` (detect v1 vs berry via `.yarnrc.yml`) |
| `package-lock.json` | `npm` |
| none + Node detected | `npm` (default) |

**Precedence when multiple lockfiles exist** (common mid-migration — e.g. leftover `package-lock.json` alongside a new `pnpm-lock.yaml`): match in table order, first match wins (`bun` > `pnpm` > `yarn` > `npm`). Presence of a stale lockfile for a non-matched manager produces a MEDIUM finding in prod-checklist with reason "migration artifact: multiple lockfiles present".

Use the detected manager consistently — do not mix. `npm audit` on a `pnpm` project fails noisily.

#### Tool-resolvability precheck

For every layer marked "will run" in the execution plan, verify the tool's binary is resolvable:
- Node: `node_modules/.bin/<tool>` or `<pm> exec <tool> --version`
- Python: `<tool> --version` from `PATH` or venv
- Go: `<tool>` from `PATH`

A layer with config present but tool not installed (e.g. `tsconfig.json` present but `typescript` not in `devDependencies`) is marked `SKIP` with reason `config present but tool not installed: <tool>`. That situation is also a MEDIUM prod-checklist finding — config drift.

Never let a layer fail with `command not found` during execution — resolve it to `SKIP` at plan time instead.

#### Network probe

One-shot HTTP HEAD request with a 3s timeout. Any HTTP response (even 4xx/5xx) counts as online — this handles corporate-proxy environments where DNS resolves but egress is selectively blocked. Timeout, DNS failure, or connection refused = offline.

Probe target precedence for monorepos (use the first detected ecosystem):
1. Node detected → `HEAD https://registry.npmjs.org/`
2. Python detected → `HEAD https://pypi.org/`
3. Go detected → `HEAD https://proxy.golang.org/`

If offline → set offline mode automatically; `dep-audit` and `license` become `SKIP` with reason `offline`.

#### Plan preview and one-beat pause

Before proceeding to Phase 2, emit the plan as a table and pause one beat. The user reads it; if it's wrong, Ctrl+C. After the pause, emit:

```
[e2e-test Nm:Ss] Phase 1/8 stack-detect — done (N ecosystems, M layers planned, K will run)
```

### Phase 2 — Increment-fit snapshot (sequential, fast)

Compute diff surface against `--ref`. Data collection only, no judgment. Feeds Phase 7.

Collect:

- Changed files list (`git diff --name-status <ref>...HEAD`)
- Changed public exports (Node: surface from `package.json[exports]`, `index.*`, `src/index.*`; Python: `__init__.py` top-level names; Go: exported names in changed `.go` files)
- Changed routes (scan for framework patterns: Express `app.get`/`app.post`/..., Fastify `fastify.route`, FastAPI `@router.get`, Gin `router.GET`, etc.)
- Changed DB migrations (`migrations/**`, `db/migrate/**`, `alembic/**`, `schema.prisma` diff)
- Changed config schemas (env-var references in `.env.example`, config files in root)
- Changed lockfile entries (new deps, version bumps)

Emit:

```
[e2e-test Nm:Ss] Phase 2/8 increment-fit — done (N files changed, M public surfaces touched)
```

### Phase 3 — Fast checks (parallel, continue-on-fail)

Run concurrently using `Bash` with `run_in_background=true` plus a non-polling streaming mechanism (the harness's `Monitor` tool or equivalent). Do NOT fall back to sleep-and-poll. If no streaming mechanism is available in the current harness, fall back to **sequential execution** of the layers in this phase and note the downgrade in the plan output (`parallelism: downgraded to sequential (no streaming tool)`). Sequential is slower but preserves correctness.

Layers in Phase 3 (filtered by the Profile × Layer matrix above; `--scope` further overrides): `types`, `lint`, `format`, `unit`, `secret-scan`, `dep-audit`. Layers not selected by the active profile or `--scope` are `SKIP`ped with reason `skipped by --profile=<X>` or `skipped by --scope`. All of these are fast (<60s typical) and non-modifying.

**Windows / MSYS fallback:** if parallel execution produces file-handle contention errors (ENOENT / EBUSY / EPERM on Windows with concurrent `node_modules` reads), retry the specific failing layer sequentially once. If the retry also fails, accept the failure and mark the layer's status accordingly. Flag in the plan output that parallelism was downgraded.

**Secret-scan patterns** (non-exhaustive; inline in v1, external tools in v1.1):

| Pattern class | Regex |
|---|---|
| AWS Access Key ID (IAM + STS) | `(AKIA\|ASIA)[0-9A-Z]{16}` |
| GitHub PAT classic | `ghp_[A-Za-z0-9]{36}` |
| GitHub PAT fine-grained | `github_pat_[A-Za-z0-9_]{82,}` |
| Stripe live key | `sk_live_[A-Za-z0-9]{24,}` |
| Slack token | `xox[baprs]-[A-Za-z0-9-]{10,200}` |
| Private key header (any type, including PKCS#8 no-type and ENCRYPTED) | `-----BEGIN( (RSA\|DSA\|EC\|OPENSSH\|PGP\|ENCRYPTED))? PRIVATE KEY-----` |
| Generic JWT | `eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` |

Scan both the tracked working tree (`git ls-files`) and the diff since `--ref` (`git diff <ref>...HEAD`). A secret committed 6 commits ago and untouched today is still in the artifact being shipped. Exclude `.env.example` (expected) and files matching `.gitignore`. If `.env` is tracked (not in `.gitignore`), that itself is a CRITICAL finding.

Emit after the phase completes (not per-layer):

```
[e2e-test Nm:Ss] Phase 3/8 fast-checks — done (types PASS, lint PASS, unit 147/150 PASS, secret-scan 0 findings, dep-audit 2 MEDIUM)
```

### Phase 4 — Integration (sequential, continue-on-fail)

Layers:

- Production build (detected command; Node uses `<pm> run build`, Python uses `python -m build` if `pyproject.toml[project]` has build config, Go uses `go build ./...`)
- Integration tests (if configured)
- Migration dry-run + reversibility check (only if Phase 2 detected schema changes). **Reversibility** is mechanical: a forward migration is reversible if ONE of — (a) an explicit down-migration file exists in the framework's convention (alembic `downgrade()`, Prisma migration `down.sql`, knex `exports.down`, Rails `change_table` with automatic reverse), OR (b) the forward migration contains ONLY additive DDL: `CREATE TABLE`, `CREATE INDEX`, `ADD COLUMN` without `NOT NULL`, `ADD COLUMN` with a default value. Everything else (`DROP COLUMN`, `DROP TABLE`, `ALTER COLUMN` narrowing a type, `ADD COLUMN NOT NULL` without default, destructive data migrations) is flagged **CRITICAL** — this is the HOLD trigger, not MEDIUM noise.

**Build failure → downstream INCONCLUSIVE.** If `build` fails and Phase 5 depends on the build artifact (e2e against a built app), Phase 5 e2e is marked `INCONCLUSIVE: build failed`. Still run Phase 5's smoke test if possible.

Emit:

```
[e2e-test Nm:Ss] Phase 4/8 integration — done (build PASS 24s, integration 34/34 PASS, migrations N/A)
```

### Phase 5 — E2E and heavy (sequential, continue-on-fail)

Layers:

- Smoke test against built artifact (if Phase 4 built)
- Playwright / Cypress e2e (if configured)
- **`--profile=deep` only:** Lighthouse CI, axe-core a11y, license audit

**If a long-running command is expected to exceed 5 minutes** (e2e, Lighthouse), emit a heartbeat BEFORE invoking:

```
[e2e-test Nm:Ss] Phase 5/8 e2e-heavy — running Playwright (expected ~8 min)
```

Then launch via `Bash run_in_background=true`, wait via the harness's streaming mechanism (no polling), emit `done` or `failed` on completion. Do NOT emit intermediate "still running" lines. Do NOT sleep-and-poll.

Emit on phase completion:

```
[e2e-test Nm:Ss] Phase 5/8 e2e-heavy — done (e2e 22/22 PASS, perf SKIP, a11y SKIP, license SKIP)
```

### Phase 6 — Production-readiness checklist (prompt-level, sequential)

Mechanical checks implemented as Claude's own pattern matching against the repo, not agent calls. **Five items in v1:**

1. **Env vars referenced but not in `.env.example`** — grep for `process.env.X`, `os.environ[X]`, `os.Getenv(X)` across source; intersect with the keys in `.env.example`. Missing keys are a finding.
2. **Secrets pattern in tracked files** — re-use the Phase 3 secret-scan regex library; run against the tracked tree (already done in Phase 3; this phase just surfaces them in the checklist dimension).
3. **Migration reversibility** — re-use Phase 4 check; if schema changes were detected and any forward migration lacks a rollback, that's a checklist finding distinct from the Phase 4 dimension.
4. **Debug noise in prod paths** — grep for `console.log`, `console.debug`, `print(`, `pprint.pprint`, `fmt.Println`, `fmt.Printf` in source files that are NOT test files (exclude paths matching `**/*test*`, `**/__tests__/**`, `**/tests/**`, `**/spec/**`, `**/*_test.*`), AND NOT inside a logger module. Logger exclusion rules — use separator-bounded patterns to avoid excluding `catalog.ts` / `blog.ts` / `changelog.ts` / `backlog.py`:
   - Path segment match: `/logger/`, `/logging/`, `/log/`
   - Exact filename match: `logger.ts`, `logger.js`, `logger.py`, `log.ts`, `log.js`, `log.py`, `log.go`, `logging.ts`, `logging.js`, `logging.py`
   - Filename pattern match: `*-logger.*`, `*-logging.*`, `*-log.ts`, `*-log.js`, `*-log.py`, `*-log.go` (hyphen-separator required)

   Findings are MEDIUM — debug noise doesn't break prod but pollutes logs.
5. **Missing error handlers at entry points** — inspect entry files (`index.*`, `main.*`, `app.*`, `server.*`, `__main__.py`, `main.go`) for top-level try/except/catch structures or framework-provided error handlers (`app.onError`, Express `(err, req, res, next)`, etc.). Entry files without any error handling are a MEDIUM finding.

**Deferred to v1.1** (per-framework awareness required):
- Rate limiting on public endpoints
- CORS / CSRF / security headers
- Feature flags for risky changes

Emit:

```
[e2e-test Nm:Ss] Phase 6/8 prod-checklist — done (5 items, 2 MEDIUM findings)
```

### Phase 7 — Synthesis (agent dispatch)

Dispatch **2 always-on + up to 3 conditional** agents. Input to each agent is pre-digested — do NOT dump raw test logs.

| Agent | Fires when | Input |
|---|---|---|
| `architect-review` REVIEW mode | Always | Diff vs `--ref`, Phase 2 increment-fit summary, list of changed public surfaces |
| `code-reviewer` | Always | Diff vs `--ref` |
| `security-auditor` | Secret-scan flagged, OR dep-audit flagged HIGH+, OR diff touches one of the specific auth-context path patterns listed below | Diff vs `--ref` (capped: file-level summary if diff >2000 lines) + dep-audit output + secret-scan output |
| `test-automator` | Any test layer failed, OR coverage dropped >5 percentage points vs `--ref`, OR zero tests in any ecosystem that has source files | Test results per layer + coverage diff |
| `performance-engineer` | `--profile=deep` AND Lighthouse/perf ran AND found regression against any configured baseline | Lighthouse JSON + Core Web Vitals + build-size diff |

**Typical dispatch: 2 agents.** Maximum: 5. Matches `/decision-map` conservatism when signal is absent, scales up only with specific signal.

**Auth-context path patterns** (for `security-auditor` trigger) — narrow by design to avoid false-firing on `tokenizer.ts`, `design-tokens.css`, `password-strength-meter.stories.tsx`:

- `**/auth/**`, `**/auth.*`, `**/authentication/**`
- `**/crypto/**`, `**/crypto.*`
- `**/session/**`, `**/session.*`
- `**/credentials.*`, `**/secrets.*`
- `**/*.pem`, `**/*.key`, `**/id_rsa*`, `**/id_ed25519*`
- `**/authorized_keys`, `**/known_hosts`
- `**/auth-token*`, `**/access-token*`, `**/refresh-token*`
- `**/password-hash*`, `**/password-reset*`
- `**/jwt*.{ts,js,py,go}`, `**/oauth*.{ts,js,py,go}`

Trigger matching is glob pattern (via the harness's glob matcher like `minimatch`) against the diff's file paths as strings — not shell-expanded.

Emit:

```
[e2e-test Nm:Ss] Phase 7/8 synthesis — done (N agents dispatched, M findings consolidated)
```

### Phase 8 — Emit (read-only)

Assemble the final report per the "Report format" section below.

**Do NOT commit. Do NOT push. Do NOT modify source files.** The only writes allowed are the two carve-outs documented in the Gates section: artifact-directory files and the one-time `.gitignore` append.

Emit the final report as a single message. Do NOT emit it incrementally.

## Verdict rules

Three verdicts. Severity gates, not counts.

### HOLD (do not ship)

Any ONE of these triggers HOLD:

- Any **CRITICAL** finding from any agent
- Any **test failure** in `unit` or `integration` layers
- **Build failure** in Phase 4
- Any **secret-scan finding** in tracked files (excluding `.env.example`, excluding `.gitignore`d paths). `.env` itself being tracked is CRITICAL.
- Any **HIGH or CRITICAL dep-audit** finding in a **production** dependency. Dev dependencies emit HIGH findings but do not block.
- **Non-reversible forward migration** when schema changes detected (per the mechanical reversibility rule in Phase 4).
- Any **increment-fit breaking change** (removed public export, renamed route, incompatible schema change) **AND NONE** of these acknowledgments present:
  - `CHANGELOG.md` diff vs `--ref` contains new bullets under `[Unreleased]` or a new version heading, OR
  - A version field changed vs `--ref` in one of: `package.json[version]`, `pyproject.toml[project.version]`, `Cargo.toml[package.version]`, `go.mod[module ... v<version>]`, `pom.xml[<version>]`, OR
  - A git tag of any form is on HEAD.

### SHIP-WITH-CAUTION (verdict: SHIP; output flags concerns)

All HOLD conditions absent, AND one or more of:

- Any HIGH finding from an agent (not already an increment-fit breaking change)
- Any HIGH dep-audit finding in a **dev** dependency
- `e2e` layer SKIP because not configured **AND** Phase 2's `Changed public exports` list is non-empty OR its `Changed routes` list is non-empty
- `integration` layer SKIP because not configured **AND** any of: Phase 2's `Changed files` touch ≥2 top-level source directories, OR `Changed public exports` non-empty, OR `Changed routes` non-empty, OR `Changed DB migrations` non-empty
- `--offline` forced skip of `dep-audit` or `license`
- `--profile=quick` was used (automatic downgrade — `quick` is not a production verdict)
- Coverage dropped >5 percentage points vs `--ref`
- Project has NO tests at all (`NOTHING-TO-TEST` advisory)

**Note on `e2e`/`integration` SKIP scoping.** A project with no `tests/integration/` directory that changes only an internal utility file is SHIP, not SHIP-WITH-CAUTION — the missing layer wasn't relevant to this increment. The trigger fires only when the skipped layer WOULD have covered the changed surface.

### SHIP (clean)

No HOLD conditions. No SHIP-WITH-CAUTION conditions. All configured layers PASS. Only MEDIUM/LOW findings present.

### Layer status legend

| Status | Meaning |
|---|---|
| `PASS` | Layer ran, no failures |
| `FAIL` | Layer ran, failures present |
| `WARN` | Layer ran, non-failing warnings only |
| `SKIP` | Layer chose not to run (flag / config / not applicable to stack) |
| `INCONCLUSIVE` | Layer could not produce a result because an upstream layer failed |
| `TIMEOUT` | Layer exceeded `--timeout` and was killed |
| `N/A` | Layer does not apply to this stack |

## Gates

- Missing `.git/` → refuse (preflight error, not verdict)
- `--ref` unresolvable → refuse (preflight error)
- Zero supported ecosystems detected with source files present → refuse (preflight error)
- Disk free <500 MB → refuse (preflight error)
- Detached HEAD without explicit `--ref` → refuse (preflight error)
- Project has zero configured test runners but source files exist → emit `NOTHING-TO-TEST` advisory; still run types/lint/secret-scan/prod-checklist; verdict is SHIP-WITH-CAUTION
- Uncommitted changes in working tree → proceed against working tree as-is; output header notes "Uncommitted changes present — this is not what was committed at any SHA." Do NOT stash.
- Re-invocation while a prior run's artifacts exist in `./.zaude/e2e-test/` → use a new timestamped subdir. Never overwrite.
- **NEVER commits, NEVER pushes, NEVER modifies source files.** The ONLY exceptions are:
  - Writes inside `./.zaude/e2e-test/<timestamp>/` (artifact directory)
  - A single-line append to `.gitignore` on first run if the file doesn't already contain `.zaude/e2e-test/`. If `.gitignore` already contains the entry, no write. If the write happens, emit a status line `[e2e-test Nm:Ss] gitignore — appended .zaude/e2e-test/ for artifact dir` before proceeding.

## Composition with other commands

- **`/build`** and **`/ship`** do not auto-invoke `/e2e-test`. Manual only. The command is too slow for every-ship use; `/review` and `/ship`'s own review chain cover pre-commit discipline.
- **`/review`** has no interaction with `/e2e-test`. Different time scales (seconds vs minutes); different goals (review the diff vs. execute the stack).
- **`/wrap`** does not auto-invoke. If you ran `/e2e-test` during the session, its artifact directory is already on disk; `/wrap` will commit project code changes but will NOT commit `./.zaude/e2e-test/` (it's gitignored).

## Progress narration

At each phase boundary, emit **exactly one** status line in this format:

```
[e2e-test Nm:Ss] Phase <N>/8 <phase-name> — <status>
```

Where `<status>` is one of:

- `starting`
- `done (<one-line summary>)`
- `failed (<one-line summary>)`
- `skipped (<reason>)`

Do NOT narrate mid-phase bash calls. Do NOT repeat status lines. Do NOT emit findings mid-run — all findings land in the final Phase 8 report.

For long-running single commands inside a phase (e2e, Lighthouse), emit ONE heartbeat before launch (`running Playwright (expected ~8 min)`), then the normal phase completion line after.

## Artifact layout

Artifacts land at `./.zaude/e2e-test/<ISO-timestamp>/`:

```
.zaude/e2e-test/2026-04-18T14-30-00Z/
├── run.log                  — full raw log of every bash invocation
├── plan.json                — execution plan produced in Phase 1
├── findings.json            — machine-readable final findings
├── report.md                — final markdown report (same content emitted to user)
├── coverage/                — coverage output from unit tests (ecosystem-specific)
├── junit/                   — JUnit XML if any test layer produced it
└── playwright-trace/        — Playwright traces if e2e ran
```

## Report format

```
## /e2e-test — production readiness report

**Verdict:** SHIP | SHIP-WITH-CAUTION | HOLD
**Profile:** <quick|default|deep>
**Ref compared against:** <ref-expression> → <resolved-sha> (<N> commits behind HEAD)
**Duration:** <Nm Ns>
**Started:** <ISO timestamp>
**Platform:** <os> / <shell> / <runtime-versions>

<If uncommitted changes in working tree:>
⚠ Uncommitted changes were present in the working tree during this run. This is not what was committed at any SHA.

---

### Execution plan (what was supposed to run)

| Layer | Planned | Reason if SKIP |
|---|---|---|
| types | YES | |
| lint | YES | |
| unit | YES | |
| integration | SKIP | no integration test dir detected |
| e2e | YES | |
| build | YES | |
| dep-audit | YES | |
| secret-scan | YES | always applicable |
| prod-checklist | YES | |
| a11y | SKIP | --profile=default (opt-in via --profile=deep) |
| perf | SKIP | --profile=default |
| license | SKIP | --profile=default |

### Execution result (what actually happened)

| Layer | Status | Detail |
|---|---|---|
| types | PASS | tsc --noEmit, 0 errors |
| lint | PASS | eslint, 0 errors, 3 warnings |
| unit | FAIL | vitest, 147/150 passed, 3 failed (see below) |
| build | PASS | 24s |
| e2e | INCONCLUSIVE | build succeeded but smoke-test failed |
| dep-audit | PASS | 0 HIGH+ in prod deps |
| secret-scan | PASS | 0 findings |
| prod-checklist | 2 MEDIUM | env var missing from .env.example, debug-log in prod path |

---

### Increment-fit analysis

Comparing HEAD (`<sha>`) against `<ref>` (`<sha>`):
- Files changed: N
- Public exports changed: <list or "none">
- Routes changed: <list or "none">
- DB migrations: <list or "none">, reversible: <yes|no|N/A>
- Config-schema changes: <list or "none">
- Breaking changes: <list or "none flagged">

---

### Findings by severity

#### CRITICAL
<none | list: file:line — reviewer — issue — recommendation>

#### HIGH
<...>

#### MEDIUM
<...>

#### LOW
<...>

---

### What was NOT tested, and why

| Layer | Reason | How to enable |
|---|---|---|
| integration | No `tests/integration/` dir or `*.integration.test.*` files detected | Add tests matching the pattern; re-run |
| a11y | `--profile=default` | Re-run with `--profile=deep` |
| license | `--profile=default` | Re-run with `--profile=deep` |

---

### Recommendation

<one of:>

**SHIP.** All configured layers passed. N MEDIUM/LOW findings present — review at your discretion before committing.

**SHIP WITH CAUTION.** <specific reason from the SHIP-WITH-CAUTION trigger list>. Proceed if <specific conditions>. Do not proceed if <specific conditions>.

**HOLD.** Blocking conditions:
- <bullet per HOLD trigger that fired>

Fix the blocking items and re-run `/e2e-test`.

---

### Artifacts

- Raw log: `./.zaude/e2e-test/<timestamp>/run.log`
- Coverage: `./.zaude/e2e-test/<timestamp>/coverage/`
- JUnit XML: `./.zaude/e2e-test/<timestamp>/junit/`
- <if e2e ran>: Playwright trace: `./.zaude/e2e-test/<timestamp>/playwright-trace/`

---

### Note on what I did NOT do

- I did NOT commit anything.
- I did NOT push anything.
- I did NOT modify any source files.
- I did NOT stash uncommitted changes — you tested what was actually in your working tree.
- <If .gitignore was appended:> I appended `.zaude/e2e-test/` to `.gitignore` to keep artifacts untracked.
```
