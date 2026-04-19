Live-audit a test run: pre-load the relevant context, stream runner events in real time, emit a ranked root-cause hypothesis list grounded in event-to-code evidence. Read-only — never writes source files, never commits. Manual invocation only.

## When to use this

- A test is failing and the stack trace alone isn't enough to find the root cause.
- A test is intermittently failing and you want a live trace the next time it fails.
- You've applied a fix and want to verify the expected code path ran.
- `/e2e-test` flagged a layer failure and you want to drill into that specific test with full instrumentation.

Do NOT use `/microscope` for:
- Fast pre-commit review (that's `/review`).
- Whole-project test suites (that's `/e2e-test`).
- Decision analysis (that's `/decision-map`).

## Arguments

```
/microscope [--test=<command>] [--focus=<path-or-symbol>]
            [--layers=<csv>] [--timeout=<seconds>]
            [--rerun=<N>] [--no-agents]
```

| Flag | Default | Semantics |
|---|---|---|
| `--test` | auto-detect from scrollback (see Phase 0) | Test command to run. Passed verbatim to `Bash`; Claude does NOT rewrite it. |
| `--focus` | auto-extracted from `--test` | Narrow Phase 1's context load to a specific file or `<file>::<test-name>` (pytest-style also accepted). |
| `--layers` | all v1-detectable | CSV of layers to instrument. v1 values: `runner`, `code`, `types`, `logs`. Unknown values → preflight refusal. (`http`, `db`, `fs` are v1.1+.) |
| `--timeout` | `600` | Per-phase timeout in seconds. Exceeded → kill process-tree, verdict `TIMEOUT`. |
| `--rerun` | `1` | Number of times to run the test. v1 only honors `--rerun=1`; higher values preflight-refuse ("flake detection is v1.1"). |
| `--no-agents` | off | Skip Phase 4 agent dispatch. Hypotheses still produced by Claude-only synthesis. |

## Phases

Six phases. No phase cancels downstream phases — every phase runs to completion; downstream dependencies are marked `INCONCLUSIVE` when upstream fails.

**Canonical phase slugs** (used verbatim in progress narration — no variation):

| Phase | Slug |
|---|---|
| 0 | `preflight` |
| 1 | `context-load` |
| 2 | `instrumentation-plan` |
| 3 | `live-execution` |
| 4 | `synthesis` |
| 5 | `emit` |

### Phase 0 — Preflight (sequential, fail-fast)

Hard prerequisites. Preflight error is NOT a verdict. Checks in order:

1. `.git/` exists at repo root. If not → refuse: `/microscope requires git for recent-diff context.`
2. Resolve target test command:
   - `--test=<cmd>` present → use verbatim.
   - `--test` absent → scan scrollback for the **most recent bash invocation that exited non-zero AND whose command matches one of the recognized runner patterns** (see §Runner detection matrix). If zero matches → refuse: `No --test provided and no recent failed test command in scrollback. Re-invoke with --test=<command>.` This is mechanical, not judgment.
3. Test command's binary is resolvable (reuse `/e2e-test` Phase 1 tool-resolvability precheck: `node_modules/.bin`, `<pm> exec <tool>`, venv, `PATH`). If not → refuse: `Binary <name> is not resolvable. Install or correct --test.`
4. Runner classification: match the test command against the regex rows in §Runner detection matrix. v1 instrumentation is tight for vitest, jest, mocha, pytest, go test, playwright, cypress. If the command matches none, **downgrade to `raw` mode** (narration emits only process start + exit code + last 3 stderr lines) — do NOT refuse. Preflight does not gatekeep on runner recognition; Phase 2's plan surfaces the degraded classification. (Config-override path at `./.zaude/microscope.config.json` is v1.1+.)
5. Free disk space ≥500 MB.
6. Unknown `--layers` value → refuse with valid-values list.
7. `--rerun >1` → refuse: `v1 only honors --rerun=1; flake detection is v1.1.`

On pass, emit:
```
[microscope 0m:00s] Phase 0/5 preflight — done (runner: <runner>, ecosystem: <ecosystem>, binary resolved)
```

### Phase 1 — Context load (sequential, bounded)

Mechanical file loads with **hard caps**. In order:

1. **Test file(s)** — from `--focus` or extracted from the test command. Always loaded in full.
2. **Test config** — `vitest.config.*`, `jest.config.*`, `playwright.config.*`, `pyproject.toml[tool.pytest]`, `conftest.py`, etc. Always loaded.
3. **Function-under-test set** — depth-1 imports from the test file (imports of imports are NOT followed). **Cap: 15 files OR 3,000 lines total**, whichever hits first. Files are loaded in order of appearance in the test file's import statements.
4. **Fixtures / mocks** — files adjacent to the test whose name matches `fixtures/`, `mocks/`, `factories/`, `conftest.py`, `setup.ts|js|py`. **Cap: 5 files.**
5. **Recent git diff** — `git diff HEAD~5..HEAD -- <paths loaded above>` (two-dot range). If `HEAD~5` doesn't exist (shallow clone, new repo), walk back via `git log` to find the earliest available prior commit. **Cap: 2,000 lines of diff.**
6. **`--layers` filter is NOT applied here.** Phase 1 is maximal context load; `--layers` only narrows Phase 2's instrumentation.

If any cap is hit, flag explicitly in the completion line:
```
[microscope 0m:02s] Phase 1/5 context-load — done (test + config + 9 impl files + 3 fixtures + 342 diff lines; function-under-test depth-1 cap hit at 15 files — use --focus to load deeper)
```

### Phase 2 — Instrumentation plan (sequential)

Produce the execution plan:
- Detected ecosystem + runner + full bash command to execute.
- Which layers will be observed in Phase 3 (per §Runner detection matrix, filtered by `--layers`).
- Which layers the runner doesn't support (auto-skip with reason).
- Rate-limit rules applied during streaming (see §Narration rate-limit).

Emit the plan as a markdown table. **Pause one beat** for user to Ctrl+C. Then:
```
[microscope 0m:04s] Phase 2/5 instrumentation-plan — done (<K> layers instrumented, <M> skipped)
```

### Phase 3 — Live execution (parallel event stream)

Launch the test via `Bash run_in_background=true`. Stream stdout + stderr via the harness's `Monitor` tool (or equivalent non-polling streaming mechanism). **Do NOT sleep-and-poll.**

**Heartbeat before any long-running command:** if the runner is playwright/cypress OR the test command includes `--timeout` ≥300s, emit BEFORE launch:
```
[microscope Nm:Ss] Phase 3/5 live-execution — launching <runner> (may exceed 5 min)
```
Then one completion line after. No intermediate "still running" lines.

**Streaming degradation:** if the harness has no streaming mechanism, fall back to synchronous `Bash` with buffered output. Phase 3 emits:
```
[microscope Nm:Ss] Phase 3/5 live-execution — streaming unavailable in this harness; running sequentially and annotating from buffered output
```
The `Streaming mode:` header in the final report labels `degraded-buffered`. Core value (context + hypothesis + artifacts) survives. This is NOT a refusal.

**On completion, emit:**
```
[microscope Nm:Ss] Phase 3/5 live-execution — <PASS|FAIL|TIMEOUT> (N/M test cases, exit <code>)
```

### Phase 4 — Synthesis (sequential)

Unless `--no-agents`, dispatch agents per §Agent dispatch matrix. Then generate the root-cause hypothesis list.

**Hypothesis grading (mechanical):**

- **HIGH** requires ALL of:
  - A streamed event directly points to a specific line in the pre-loaded context (file:line cited from the runner output).
  - AND either (a) that line is in the recent diff loaded in Phase 1, OR (b) the line has a structural bug visible without execution (missing return, null deref on un-null-checked parameter, off-by-one in a loop bound, unhandled error path).
- **MEDIUM**: event→context link exists but no diff corroboration and no visible structural bug — a reasoned inference rather than a direct match.
- **LOW**: reasonable guess not directly supported by streamed events (e.g. "environment variable might be misconfigured" without evidence).

**Ordering:** HIGH first, then MEDIUM, then LOW. Max 5 hypotheses total. If zero hypotheses pass HIGH/MEDIUM thresholds, emit LOW-only list under a prominent header: `No high-confidence hypothesis — evidence is thin. Consider re-invoking with --focus to load more context.`

**Each hypothesis must cite:**
- File:line with a 3–5 line code snippet.
- Streamed event timestamp (from the live trace).
- Fix sketch (pseudocode or prose; NOT a diff — this command never writes).
- How to verify the fix (the exact re-invocation to prove the hypothesis).

> **JUDGMENT CALL:** when two hypotheses tie on evidence strength, tiebreak by recency of the cited diff commit (more recent wins). If still tied, present both at the same rank and let the user decide.

**Do NOT emit a hypothesis that cites code outside Phase 1's loaded set.** If a hypothesis would require inspecting a file not loaded, flag it as `unexplored — Phase 1 cap hit; re-invoke with --focus=<path> to load and analyze`.

Emit:
```
[microscope Nm:Ss] Phase 4/5 synthesis — done (<N> agents dispatched, <T> hypotheses: <H> HIGH / <M> MEDIUM / <L> LOW)
```

### Phase 5 — Emit (read-only)

Assemble the report per §Report format. **Single message, not incremental.** Write artifacts to `.zaude/microscope/<ISO-timestamp>/` (see §Artifact layout). On first run, append `.zaude/microscope/` to `.gitignore` with an announce line — same one-time carve-out pattern as `/e2e-test`.

**Do NOT commit. Do NOT push. Do NOT modify source files.** The only filesystem writes are (a) the timestamped artifact directory, and (b) the one-time `.gitignore` append.

## Streaming-mechanism contract

| Tier | Mechanism | Phase 3 behavior | Report header |
|---|---|---|---|
| Ideal | `Bash run_in_background=true` + `Monitor` (or equivalent) | Live narration per rate-limit rules below | `Streaming mode: live` |
| Fallback | `Bash` synchronous + full buffered output | Phase 3 emits only start + completion lines; annotations derived post-hoc from the buffer | `Streaming mode: degraded-buffered` |

**Hard constraint: no sleep-and-poll.** Same rule as `/e2e-test`. A harness that neither supports streaming nor synchronous Bash cannot run `/microscope` — but that configuration is not expected in practice.

## Runner detection matrix

v1 runners. Each row defines the regexes the skill uses to classify streamed events. All regexes are ANSI-stripped and CRLF-normalized before matching.

| Runner | Start-of-run | Test start | Pass | Fail | Assertion/error | Hook phase |
|---|---|---|---|---|---|---|
| vitest | `^RUN`, `^Tests` | `^ ?([✓×↓⋯])`, `^ ?(PASS\|FAIL)` | `^✓`, `^ ?PASS` | `^×`, `^ ?FAIL` | `AssertionError`, `Error:`, `^ *at ` stack | `beforeAll`, `afterAll`, `beforeEach`, `afterEach` |
| jest | `^PASS`, `^FAIL`, `^Test Suites` | `^  ✓`, `^  ✗` | `^  ✓`, `^PASS` | `^  ✗`, `^FAIL`, `^  ●` | `Error:`, `● ` summary blocks | same as vitest |
| mocha | `passing`, `failing` | `^  ✓`, `^  ✗` | `^  ✓`, `passing` | `^  ✗`, `failing` | `AssertionError`, stack frames | `before`, `after`, `beforeEach`, `afterEach` |
| pytest | `^=+ test session starts`, `collected` | `^([A-Za-z_./].+::)` | `PASSED` | `FAILED`, `ERROR` | `^E  `, `assert`, `Traceback`, `^>   ` | `@pytest.fixture`, `setUp`, `tearDown` |
| go test | — (no explicit banner; first `=== RUN` is the first test-start) | `^=== RUN   ` | `^--- PASS: ` | `^--- FAIL: ` | `^\t.+\.go:\d+:` | `TestMain`, `t.Cleanup` |
| playwright | `^Running \d+ tests`, `^ *[✓✗]` | `^ *[✓✗] *\d+ ` | `^ *✓ ` | `^ *✗ ` | `Error: `, `expect(`, stack frames | `beforeAll`, `afterAll`, `test.beforeEach` |
| cypress | `cy:command`, `passing`, `failing` | `^  ✓`, `^  ✗` | `^  ✓`, `passing` | `^  ✗`, `failing` | `CypressError`, `AssertionError`, stack | `before`, `beforeEach`, `after`, `afterEach` |

**Unrecognized runner:** fall back to `runner=raw`. Narration emits only start + "process exited with code N" + last 3 stderr lines. Phase 4 relies entirely on Phase 1 pre-loaded context + the buffered output. The report header labels `Runner: raw (unrecognized)`.

> **JUDGMENT CALL:** if a streamed line matches regexes for multiple classes (e.g. a pass line that also contains "Error" as literal text), classify as the more-specific class first (Fail > Error > Pass > Start). If still ambiguous, emit both classifications in the live trace with a note, and let Phase 4 synthesize.

## Narration rate-limit

Claude emits **at most one annotation per streamed event class per event**. Everything else is collapsed silently — the full stream still lands in `run.log` and `events.jsonl`.

| Event class | Emit rule |
|---|---|
| Runner start | Once per run |
| Test case start | Once per test |
| Test case result | Once per test (PASS/FAIL/SKIP with file:line extracted if runner emits it) |
| Assertion failure | Once per failure, with file:line extracted |
| Error / exception | Once per error, with location extracted |
| Hook phase | Once per hook invocation |
| Everything else (console.log, progress bars, banner lines) | **Silent** — not narrated |

**Rationale for the silent default:** a noisy test suite can emit thousands of console.log lines. Annotating every line would blow the token budget. The full trace is retrievable from `events.jsonl` post-run.

## Failure-mode catalog

**Preflight REFUSE** (command does not run; not a verdict):

| Condition | Refusal reason |
|---|---|
| Missing `.git/` | Requires git for diff context |
| `--test` absent AND no scrollback match | Re-invoke with `--test=<command>` |
| Test binary not resolvable | Install or correct `--test` |
| Disk free <500 MB | Insufficient disk for artifacts |
| `--layers=<csv>` has unknown values | Valid: runner, code, types, logs |
| `--rerun >1` | v1 only honors --rerun=1 |

**In-flight DEGRADE** (command runs, flagged in output):

| Condition | Flag in output |
|---|---|
| Streaming unavailable | `Streaming mode: degraded-buffered` |
| Phase 1 cap hit | `function-under-test depth-1 cap hit at <N> files` |
| Shallow clone (HEAD~5 unavailable) | `Diff window truncated at HEAD~<K>` |
| Runner is `raw` (unrecognized) | `Runner: raw (unrecognized)` — hypothesis section flags reduced signal |
| Agent call fails or not installed | Flag in Agent findings section; never halt |
| Phase 1 timeout exceeded | Partial context loaded; Phase 3 still runs against what was loaded; hypothesis section flags `reduced context — Phase 1 timeout exceeded`. Matches the continue-on-fail invariant. |

**Pass-case:** always runs to full completion. `Outcome: PASS`, hypothesis section becomes `Nothing notable observed. Test passed; trace available in artifacts.` No refusal to run on passing tests — confirming a fix is a valid use.

**Command NEVER:**
- Commits or pushes.
- Modifies source files.
- Applies fixes suggested by hypotheses.
- Re-runs the test after emitting hypotheses (user drives the iteration).
- Writes anywhere outside `.zaude/microscope/<timestamp>/` except a one-time `.gitignore` append.

## Agent dispatch matrix (Phase 4)

| Agent | Fires when | Input |
|---|---|---|
| `code-reviewer` | Always (unless `--no-agents`) | Phase 1 context (test + function-under-test + fixtures) + streamed events + top-3 hypotheses |
| `debugger-readonly` | Always (unless `--no-agents`) — paired with `code-reviewer` | Same as `code-reviewer` plus the live trace events JSONL |
| `security-auditor` | Test file OR function-under-test path matches the same auth-context glob list as `/e2e-test` (`**/auth/**`, `**/auth.*`, `**/authentication/**`, `**/crypto/**`, `**/crypto.*`, `**/session/**`, `**/session.*`, `**/credentials.*`, `**/secrets.*`, `**/*.pem`, `**/*.key`, `**/id_rsa*`, `**/id_ed25519*`, `**/authorized_keys`, `**/known_hosts`, `**/auth-token*`, `**/access-token*`, `**/refresh-token*`, `**/password-hash*`, `**/password-reset*`, `**/jwt*.{ts,js,py,go}`, `**/oauth*.{ts,js,py,go}`) | Context + diff within auth-context paths |
| `architect-review` REVIEW mode | Claude's hypothesis cites ≥2 modules as the bug location (cross-module interface failure) | Hypothesis text + cross-module files |
| `postgres-pro-readonly` | Test-under-scope hits `.sql` / migrations / Postgres-specific code paths (per `agent-usage.md` dispatch trigger) | Phase 1 DB-related files + streamed SQL events |
| `python-pro-readonly` | Runner = pytest AND `--focus` contains `*.py` OR Phase 1 loaded >200 Python lines | Phase 1 Python files + streamed test events |
| `react-specialist-readonly` | Runner = vitest/jest/playwright/cypress AND test-file is `*.test.tsx`/`*.spec.tsx` AND project has React >=18 | Phase 1 React files + streamed render/hook events |

**Dispatch cap: 5 agents.** Typical run: 2 (`code-reviewer` + `debugger-readonly`). Max: 5.

> **Closed in v0.5:** earlier versions noted "no dedicated debugger agent in the roster — Claude itself orchestrates." This gap is now closed by `debugger-readonly` as an always-on Phase 4 specialist. The command's hypothesis quality improves with a debugger-specialist reviewing alongside `code-reviewer`.

**Missing agent:** flag in Agent findings section, proceed. Never halt.

**`--no-agents` override:** skip Phase 4 agents entirely. Hypotheses still produced by Claude-only synthesis. Useful for fast iteration on a known-bug-location where re-review is noise.

## Artifact layout

```
.zaude/microscope/<ISO-timestamp>/
├── run.log                — full raw stdout+stderr of the test command
├── plan.json              — Phase 2 instrumentation plan
├── hypotheses.json        — hypothesis list with confidence + evidence pointers
├── report.md              — final markdown report (same content emitted to user)
├── events.jsonl           — line-delimited JSON of every streamed event with timestamp + class
└── context/               — every file loaded in Phase 1 (for post-hoc reproducibility)
    ├── test-file-<n>.ts
    ├── impl-<n>.ts
    ├── fixtures-<n>.ts
    └── diff.patch         — git diff HEAD~N..HEAD on the context paths
```

Timestamp format: ISO 8601 with colons replaced by dashes (e.g. `2026-04-18T14-30-00Z`) for cross-platform filesystem safety.

On first run, append `.zaude/microscope/` to `.gitignore` if not already present. Emit:
```
[microscope Nm:Ss] gitignore — appended .zaude/microscope/ for artifact dir
```

## Gates

- Preflight refusals (see Failure-mode catalog) → command does not run.
- **NEVER commits, NEVER pushes, NEVER modifies source files.** The ONLY exceptions are writes inside `.zaude/microscope/<timestamp>/` and a one-time `.gitignore` append.
- **NEVER applies fixes.** Hypothesis section includes fix sketches; user is the authoring gate.
- **NEVER re-runs the test after emitting hypotheses.** User drives iteration.
- Agent failures degrade gracefully — never halt the command.

## Composition with other commands

- **`/build`**, **`/review`**, **`/ship`**, **`/wrap`**, **`/decision-map`** — all orthogonal. None auto-invoke `/microscope`; `/microscope` never auto-invokes any of them. Purely manual.
- **`/e2e-test`** — orthogonal in v1 (no auto-invoke in either direction). `/e2e-test`'s HOLD verdict recommendation includes a copy-paste suggestion line of the form `Drill further: /microscope --test="<failing-layer-command>"` — this is a suggestion only, not an auto-invocation. A v1.1 `/e2e-test --drill-on-fail=<layer>` opt-in may be added later.

## Report format

```
## /microscope — <test-command>

**Outcome:** PASS | FAIL | TIMEOUT | INCONCLUSIVE
**Runner:** <runner-name or `raw (unrecognized)`>
**Ecosystem:** <node|python|go>
**Streaming mode:** live | degraded-buffered
**Duration:** <Nm Ns>
**Platform:** <os> / <shell>
**Started:** <ISO timestamp>

---

### Pre-flight context loaded

| Context | Loaded | Cap hit? |
|---|---|---|
| Test file(s) | <paths> | no |
| Test config | <paths> | no |
| Impl files (depth-1) | <N files, M lines> | <yes/no; if yes, which truncated> |
| Fixtures/mocks | <N files> | no |
| Recent git diff (HEAD~5..HEAD) | <N lines / M files> | no |

---

### Instrumentation plan

| Layer | Status | Reason if SKIP |
|---|---|---|
| runner | INSTRUMENTED | — |
| code | INSTRUMENTED | — |
| types | INSTRUMENTED | — |
| logs | INSTRUMENTED | — |
| http | SKIP | v1 does not support HTTP instrumentation for <runner> |
| db | SKIP | no ORM log hook detected |
| fs | SKIP | v1 does not support FS instrumentation |

---

### Live trace (chronological)

[microscope 0m:00s] Phase 0/5 preflight — done (runner: vitest, ecosystem: node)
[microscope 0m:02s] Phase 1/5 context-load — done (...)
[microscope 0m:04s] Phase 2/5 instrumentation-plan — done (...)
[microscope 0m:05s] Phase 3/5 live-execution — starting (<bash command>)
[microscope 0m:06s]   beforeAll hook started
[microscope 0m:06s]   test "<name>" PASSED
[microscope 0m:06s]   test "<name>" FAILED at <file>:<line>
[microscope 0m:07s]   afterAll hook ran
[microscope 0m:08s] Phase 3/5 live-execution — FAIL (1/2 passed, exit 1)
[microscope 0m:10s] Phase 4/5 synthesis — done (1 agent dispatched, 2 hypotheses: 1 HIGH / 0 MEDIUM / 1 LOW)
[microscope 0m:10s] Phase 5/5 emit — writing report

---

### Root-cause hypotheses

#### 1. HIGH — <one-line claim>

**Evidence:**
- Streamed event `<event description>` at `<Nm:Ss>`
- Source `<file>:<line-range>`:
  ```<lang>
  <3–5 line snippet>
  ```
- Recent diff: commit `<sha>` (<time-ago>) <what changed at this location>.

**Fix sketch:** <prose description of the fix — NOT a diff>

**Verify:** <exact re-invocation to prove the hypothesis>

#### 2. MEDIUM — <claim> (or LOW)

(same structure; omit sections that don't apply)

---

### Context snapshot

- **Test file:** <path> (<N> lines, <M> test cases)
- **Function under test:** `<symbol>` at `<file>:<line-range>`
- **Fixtures loaded:** <paths>
- **Git diff window:** `HEAD~<N>..HEAD` (<N> commits, <M> lines across <K> files)
- **Most relevant diff:** commit `<sha>` by <author>, <time-ago>, "<subject>"

---

### Agent findings

<code-reviewer output, if fired>
<security-auditor output, if fired>
<architect-review output, if fired>
<Or: "No agents fired (--no-agents).">

---

### What was NOT instrumented, and why

| Layer | Reason | How to enable |
|---|---|---|
| http | Not supported for <runner> in v1 | v1.1 planned |
| db | No ORM log hook detected | Configure ORM query logging in test setup |
| fs | Not supported in v1 | Not planned |

---

### Artifacts

- Raw run log: `./.zaude/microscope/<timestamp>/run.log`
- Plan: `./.zaude/microscope/<timestamp>/plan.json`
- Hypotheses: `./.zaude/microscope/<timestamp>/hypotheses.json`
- Events (JSONL): `./.zaude/microscope/<timestamp>/events.jsonl`
- Context snapshot: `./.zaude/microscope/<timestamp>/context/`
- Report: `./.zaude/microscope/<timestamp>/report.md`

---

### Note on what I did NOT do

- I did NOT write or modify any source file.
- I did NOT apply any fix from the hypothesis list.
- I did NOT re-run the test after emitting hypotheses.
- I did NOT commit or push anything.
- <If --no-agents:> I did NOT dispatch any agents.
- <If context cap hit:> Phase 1's <N>-file / <M>-line cap was hit. Hypotheses are bounded by what I loaded. Re-invoke with `--focus=<path>` to load additional context.
- <If streaming degraded:> Streaming was unavailable; Phase 3 ran synchronously with annotations derived post-hoc.
```

## Cross-platform notes

Inherits `/e2e-test`'s lessons:

- Paths in output are POSIX-style (forward slashes) even on Windows.
- ANSI escape sequences are stripped before regex matching (runners emit color codes).
- CRLF is normalized to LF before regex matching on Windows Git-Bash / MSYS.
- Streaming on Git-Bash has been validated via `/e2e-test` Phase 3; assume it holds here. Fallback is the buffered-degraded mode.

**New concern specific to `/microscope`:**

- Playwright and Cypress spawn browser sub-processes. Killing on `--timeout` must kill the process-tree, not just the parent. `Bash` tool's background-process cleanup is expected to handle this; if it doesn't, the browser may remain running and show up as a LOW finding in the artifact (`browser process not fully cleaned up`). Manual cleanup documented in artifact notes.
- PowerShell users should prefer single-file test commands over complex `-k "expr"` quoted patterns in v1 (quoting is fragile across PowerShell → Git Bash → runner).
