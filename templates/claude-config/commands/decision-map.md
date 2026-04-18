Produce a structured decision map for a technical decision. Read-only by default — NEVER writes to `decisions.md`; never writes to any file on disk. Output is a markdown report the user reads and optionally copies.

## Arguments

`$ARGUMENTS` — the decision question, optionally followed by flags:

- `--revisit` — bypass the "already-settled" refusal. Requires a rationale clause in `$ARGUMENTS` (see Step 0 for the mechanical check). If passed without detectable rationale, the command refuses.
- `--force` — bypass the "insufficient context" refusal. Use only when you knowingly want analysis against a thin vault. Confidence is automatically capped at `low`.
- `--draft-decision` — include a pre-formatted `decisions.md` entry block in the output. Still print-only. The command never writes to `decisions.md`, flag or no flag.

If `$ARGUMENTS` is empty, STOP and emit the usage hint (see "Refusal outputs" below).

## Scope

This command is for **technical decisions only**: architecture, library choice, schema design, API shape, test strategy, refactor scope, dependency choice, error-handling patterns, service boundaries. It is NOT for product, process, people, hiring, pricing, timing, or scope-of-work decisions. If the question is ambiguous between technical and non-technical, treat as non-technical and refuse — don't analyze a product decision in technical costume.

## Steps

### 0. Scope classifier — always first

Apply these checks in order. The first one that matches determines the outcome. No tool calls, no file reads, no agent dispatches — answer from prompt and loaded context only. Outcomes are evaluated as an ordered checklist, not a partition; a question can be both technical and settled, so order matters.

1. **Empty `$ARGUMENTS`?** → STOP, emit usage hint.
2. **Non-technical decision?** If the question is a product / process / people / timing / pricing / hiring decision, or is genuinely ambiguous between technical and non-technical → REFUSE with the scope-refusal output. Do not analyze.
3. **Already-settled without revisit rationale?**
   - "Settled" = `decisions.md` contains an entry that **directly answers this question** (not just a neighboring topic).
   - If settled AND `--revisit` was NOT passed → REFUSE with the settled-decision output.
   - If settled AND `--revisit` was passed: inspect `$ARGUMENTS` for a rationale clause. A rationale clause contains at least one of these signals: `because`, `since`, `now that`, `new constraint`, `new information`, `changed`, `different`, `no longer`, `has fired`, or an explicit reference to the prior entry's own documented revisit trigger. If no such clause is present → REFUSE with the settled-decision output and tell the user to re-invoke with the rationale inline.
4. **Insufficient vault context?** REFUSE if ANY of:
   - `spec.md` is missing or empty, OR
   - No relevant `CLAUDE.md` rule applies AND no `architecture.md` AND no neighboring precedent in `decisions.md`.

   **Override:** if `--force` was passed, skip this refusal, proceed to Step 1, and cap Step 7 confidence at `low`. `--force` bypasses ONLY this Step 0.4 refusal; it does NOT bypass Steps 0.1 / 0.2 / 0.3.
5. **Otherwise** → proceed to Step 1.

### 1. Decision-type classification

Pick exactly one type: `structural | data | api | security | perf | test | refactor | dependency | other`.

**Security override:** if `$ARGUMENTS` contains any of these tokens — `auth`, `token`, `password`, `crypto`, `ssh`, `credential`, `secret`, `session`, `jwt`, `oauth`, `encryption` — force classification to `security` regardless of the top-level read. Over-firing `security-auditor` is cheap; under-firing is a risk.

If classification is genuinely ambiguous between two types, pick one and say so explicitly in the output. Do not fire multiple specialists to hedge.

### 2. Vault precedent scan

The `SessionStart` hook has already loaded the vault into context. Do NOT re-read files from disk — use what's in context.

Scan for:

- **`decisions.md`** — semantic neighbors of the question. Surface up to 3 closest prior decisions with date + outcome + one-line rationale. If precedent contradicts the direction the user's phrasing implies, **lead with that** in the Context section.
- **`open-questions.md`** — related unresolved questions. Flag bundling opportunities.
- **`CLAUDE.md`** — hard rules that constrain the option space. If a rule disqualifies an option the user named, lead with that.
- **`spec.md`** — pull 1–2 lines describing what the project IS. Anchor the "Taste / principles" note.

If the precedent scan finds no relevant vault content AND the question has no obvious answer from `CLAUDE.md` hard rules alone, treat as "insufficient context" and refuse.

### 3. Enumerate options

Rules the command enforces on itself:

- **Include options the user named verbatim.** Do not silently rename them to "better" names.
- **Always include "do nothing / keep current"** — even when the user didn't name it.
- **Always include "defer with trigger"** — the trigger must be a concrete, observable condition (e.g. "when we scale past 1 dyno", "when the second team adopts this API"), not "revisit later".
- **Include at most one hybrid option**, and only if it is materially different from the named options. A weighted average of A and B is not a hybrid; a genuinely third architecture is.
- **Refuse to invent filler.** If only two sane options exist, output has two plus defer. If only one sane option exists, say so — recommendation is that option, confidence assessed per Step 7, and the rest of the map (precedent, hard rules, rollback, revisit trigger) still runs. No padding.
- **Present options in alphabetical order by assigned name.** Assign each option a short name (e.g. "Postgres", "SQLite", "Redis-backed"); sort alphabetically by that name; assign letter identifiers A/B/C in sorted order. This destroys the user's phrasing bias deterministically. Note the reordering explicitly in the final "Note on what I did NOT do" section.

### 4. Specialist dispatch — sequential, max 2 agents

Always fire `architect-review` in **DESIGN mode** first. Pass it the question, the options list, the relevant hard rules from `CLAUDE.md`, and any precedent surfaced in Step 2.

Then conditionally fire ONE additional agent, sequentially (not in parallel), using the first agent's output plus the options list as input:

| Classification | Second agent | Trigger |
|---|---|---|
| `security` | `security-auditor` | Always |
| `perf` | `performance-engineer` | Always |
| `test` | `test-automator` | Always |
| `data` | `security-auditor` | Schema includes PII, auth, credentials, or tokens |
| `api` | `security-auditor` | API is public, auth'd, or accepts untrusted input |
| `refactor` | `test-automator` | Refactor crosses module boundaries OR touches >10 files |
| `dependency` | `security-auditor` | Dependency handles auth, crypto, input parsing, or network I/O |
| `structural`, `other` | None | — |

**Hard cap: two agents per invocation.** If the decision legitimately needs three or more specialist dimensions, note explicitly in the output: "This decision has <X, Y, Z> dimensions. I ran <architect-review, second-agent>; the <third> dimension was not analyzed. Consider a follow-up `/decision-map` framed around the <third> tradeoff."

**Missing agent handling:** if a named specialist agent is not installed on the user's machine, skip it, and flag the missing dimension in the Analysis section ("security-auditor not installed; security dimension not analyzed — do not adopt this recommendation without independent security review"). Never halt.

### 5. Score each option

**Load-bearing criteria — always present in the Analysis table:**

1. **Reversibility** — label, not a score: `2-way door` (easy to undo) or `1-way door` (hard/expensive to undo).
2. **Blast radius** — S / M / L / XL. Quantify when possible (files, services, users affected).
3. **Implementation cost** — rough bucket: hours / days / weeks. One bucket per option.
4. **Hard-rule compliance** — PASS / TRADEOFF / FAIL. If TRADEOFF or FAIL, cite the specific rule verbatim. Any FAIL eliminates the option unless the user explicitly overrides the rule.
5. **Primary risk** — one-sentence description of the worst realistic failure mode.

**Situational criteria — include a row only when relevant to the decision:**

- **User impact** — include only when the decision has external-facing consequences (breaking API change, UX change, performance regression users will feel).
- **Maintenance burden** — include only when options differ materially on ongoing cost.
- **Migration safety** — include only for `refactor` or `data` classifications.

**Strategic fit is NOT a scoring criterion.** If a judgment call was made that the table doesn't capture, name it explicitly in the Recommendation section's "Taste / principles note" line.

### 6. Anti-sycophancy pre-emit self-check

Before printing the map, run this two-line self-check:

1. Did I pick the option the user named first? If yes, am I certain the alphabetical-reorder preserved my neutrality, or am I rubber-stamping?
2. Did I hedge the recommendation to avoid contradicting the user's phrasing? If the honest recommendation is "none of your options are right," did I say that explicitly?

If either check fails, revise the map before emitting.

### 7. Confidence calibration

Apply these rules in order; caps stack (the lowest ceiling wins):

- **`high`** requires ALL THREE of:
  - precedent in `decisions.md` agrees with the recommendation,
  - applicable hard rules in `CLAUDE.md` / `spec.md` are unambiguous,
  - primary risk is low or medium (not high/XL).
- **If a specialist that the Step 4 matrix WOULD have dispatched failed to run** (not installed or errored) → maximum confidence is `medium`. Classifications with no matrix entry (`structural`, `other`) are **not** penalized — nothing was meant to fire.
- **If `--force` was used** to bypass the insufficient-context refusal → maximum confidence is `low`.
- **If `--revisit` was used** and the rationale clause is present but thin (one signal word, no substance) → maximum confidence is `low`.
- **`low`** when the analysis itself is shaky — thin vault, conflicting signals, or the honest answer is "need more data."
- Otherwise `medium`.

Do not inflate confidence to make the recommendation feel more decisive. A `medium` recommendation honestly labeled is worth more than a `high` one that hides its uncertainty.

### 8. Emit — read-only

Print the decision map using the format in "Report format" below.

**No file writes. No commits. No appends to any vault file.**

If `--draft-decision` was passed, append a pre-formatted `decisions.md` entry block at the end of the output — still print-only, purely for the user to copy if they adopt the recommendation.

## Gates

- `$ARGUMENTS` empty → STOP with usage hint
- Scope classifier → non-technical decision → REFUSE, do not analyze
- `decisions.md` has a settled entry directly answering the question AND `--revisit` not passed (or passed without rationale clause) → REFUSE, surface the existing entry
- Vault context insufficient (predicate: `spec.md` missing/empty, OR no relevant `CLAUDE.md` rule AND no `architecture.md` AND no neighboring precedent) AND `--force` not passed → REFUSE with list of missing pieces
- Every option FAILs on hard-rule compliance → STOP; tell the user the option space is empty under current constraints and ask whether to propose new options or override a rule
- Specialist agent errors or times out → degrade gracefully (partial map + flag missing dimension); never halt
- **NEVER write to `decisions.md`** — that file is human-authored, append-only, and sacred. `/decision-map` may propose draft entries, never commit them.
- **NEVER auto-append to `open-questions.md`** — the draft QN block in the output is for the user to copy. The command does not touch disk.

## Composition with other commands

- **`/build`** does not auto-invoke `/decision-map`. If `workflow-orchestrator` surfaces an ambiguous architectural choice during `/build`, it may *suggest* `/decision-map <question>` in its plan output. The user decides whether to break off.
- **`/decision-map` → `/build` (on adoption).** When an adoption signal fires (see "Post-recommendation behavior"), Claude treats the work as an implicit `/build <recommended-option-description>`. Same review chain, same gates. The inverse direction (`/build` → `/decision-map`) is NOT wired; `/build` only suggests, never invokes.
- **`/review`** and **`/decision-map`** have no interaction. `/review` is post-facto on code; `/decision-map` is pre-facto on a question. Invoking `/review` between the map emit and an adoption signal closes the adoption window — a later `go` is ambiguous.
- **`/ship`** is the commit step for adopted `/decision-map` work. Adoption authorizes the work; `/ship` authorizes the commit (two-step). Reviewer findings during `/ship` that raise architectural questions (not code defects) may suggest `/decision-map` as remediation; not automated.
- **`/wrap`** does not currently have a wired prompt for decisions adopted from `/decision-map`. If you adopted a recommendation this session, you are responsible for appending the entry to `decisions.md` by hand before `/wrap` runs its "append decisions" step. A future Zaude release may wire this handshake explicitly into `/wrap` step 4.

## Report format

**Structural rule: the Recommendation is the LAST section emitted.** Context, options, analysis, drafts, and housekeeping come before it. The user's eye should land on the recommendation as the closing line of the document — that's where the action signal is.

```
## Decision: <restated question, canonicalized>

**Classification:** <type>
**Analyzed by:** architect-review<, additional-agent if fired>

---

### Context
<1 short paragraph: what's being decided, what constrains it, what's already true>

**Hard rules that apply:**
- <CLAUDE.md rule, verbatim quote, with a note on which options it constrains>
- (or: "None bearing on this decision.")

**Precedent in vault:**
- <decisions.md YYYY-MM-DD: 1-line prior decision + outcome> — relevance: <why it matters here>
- (or: "No prior precedent. This is a first-of-its-kind call.")

**Related open questions:**
- <open-questions.md Q7: summary> — bundling opportunity: <yes/no + why>
- (or: "None.")

---

### Options
<Alphabetical by assigned name. Each option: identifier + descriptive name + 2–3 sentences.>

**A — <name>**
<2–3 sentences. What it is, what it does, what's distinctive about it.>

**B — <name>**
<2–3 sentences.>

**Defer**
Trigger to revisit: <concrete condition>. Cost of deferring: <what we lose by waiting>.

---

### Analysis

<Use the table when all options are structurally comparable (same shape of thing).
Omit the table and use per-option prose when options are structurally unequal
(e.g. "keep current vs rewrite in Rust"). Criteria are still named, just not tabulated.>

| Criterion | A | B | Defer |
|---|---|---|---|
| Reversibility | 2-way door | 1-way door | 2-way |
| Blast radius | S (3 files) | L (12 files, 2 services) | — |
| Impl cost | ~2h | ~2d | 0 |
| Hard-rule compliance | PASS | TRADEOFF (rule: "No mock data") | PASS |
| Primary risk | Local-only, low | Migration can't roll back mid-flight | Decision pressure builds |

<Situational rows appear here only when relevant: User impact | Maintenance burden | Migration safety.>

<Mermaid decision tree — OMIT unless there are ≥3 options AND branching logic is non-trivial. A 2-option table does not need a tree.>

---

### Draft entry for open-questions.md

<Pre-formatted Q<N> block using the template at the bottom of open-questions.md.
Print-only — the user copies if they want formal tracking.>

<If --draft-decision was passed, append:>

### Draft entry for decisions.md (print-only — I never write to decisions.md)

<Date-stamped entry in the project's decisions.md format: decision + rationale + implications. For the user to review and commit by hand if they adopt the recommendation.>

---

### Note on what I did NOT do

- I did NOT write to `decisions.md`.
- I did NOT commit anything.
- I did NOT append to `open-questions.md` (the draft block above is for you to copy).
- <If filler options were rejected:> I considered and rejected <option Y> because <reason>.
- Options are presented alphabetically by assigned name, not in the order you named them, to neutralize phrasing bias.

---

### Recommendation

**<Option X>** (confidence: <high | medium | low>)

**Why:** <2–3 sentences grounded in specific rows of the Analysis table. No new reasoning — synthesis only.>

**Primary tradeoff:** <what you're giving up by picking X.>

**Taste / principles note:** <if the recommendation involved a judgment call not captured in the table, name it here. Example: "I weighted reversibility over impl cost because the vault shows a pattern of regret on 1-way doors chosen for speed." Omit this line if no judgment call was involved.>

**Rollback plan:** <concrete steps if X proves wrong within 2 weeks. Not "we'll revert" — actual steps: what to undo, what to restore, what to communicate.>

**Revisit trigger:** <the concrete, observable signal that would invalidate this recommendation and warrant a new `/decision-map`.>

**Invitation line — conditional on whether the recommendation is Defer:**

- If the recommended option is **not** Defer: `Reply `go` to start implementing Option X. Reply `go with <letter-or-name>` to adopt a different option, or redirect with a new constraint to re-analyze.`
- If the recommended option **is** Defer: `Reply `go` to adopt Defer — I'll acknowledge and print the revisit trigger; no implementation. Reply `go with <letter-or-name>` to adopt a non-Defer option instead, or redirect with a new constraint to re-analyze.`
```

## Post-recommendation behavior

After emitting the report, Claude watches for the user's next reply. The report ends with an explicit invitation to reply `go` to adopt the recommendation. The adoption contract below is mechanical — no judgment calls, no substring matches.

### Signal recognition — strict token match

Strip the user's reply of leading/trailing whitespace and trailing punctuation (`.`, `!`, `?`). Compare case-insensitively against these exact patterns (nothing more, nothing less):

**Bare adoption → adopt the recommended option:**
- `go`
- `yes`
- `approved`
- `implement it`

**Named adoption → adopt option X (where X is a letter `A`/`B`/`C`/... or the full option name including `Defer`):**
- `go with <X>`

If X equals the recommended option's identifier, the effect is identical to bare adoption. If X differs, adopt X instead — which may trigger the Defer special case below if X is Defer.

(`adopt <X>` is deliberately NOT in the signal set — `go with <X>` is the single canonical named-adoption form. One phrasing, no drift.)

**Rejection / redirect → do NOT adopt; wait for new direction:**
- `no`
- `reject`
- `try again`
- `revisit with <new constraint>`

**Anything else → wait.** Examples that do NOT match:
- `go check the README` — reply contains non-token text → wait (this is the reason strict-match exists)
- `yes but option A` — hedged reply → wait; ask for clarification
- `proceed`, `ship it`, `do it` — explicitly NOT in the signal set; `proceed` collides with Zaude's destructive-action announcement closer ("Proceeding in one beat…"), `ship it` collides with the `/ship` command, `do it` is ambiguous. If the user wants to adopt, they use one of the four bare tokens above.

Option-identifier match is case-insensitive (`go with a` = `go with A` = `go with Defer` = `go with defer`).

### Scope — mechanical turn-adjacency rule

The adoption signal fires ONLY when ALL of these hold:

1. The `/decision-map` output was emitted in Claude's immediately-preceding turn (the turn just before the user's reply being evaluated).
2. No intervening user turn exists between the map emit and the reply — not a clarifying question, not a slash command, not anything. One turn, one chance.
3. The reply is a strict token match per the signal-recognition rules above.

If the user invokes another slash command, asks a clarifying question in a separate turn, or replies with anything non-matching first, the adoption window closes. A subsequent `go` is no longer an adoption signal — Claude must ask what it refers to.

### Defer special case

When the adopted option is **Defer** (whether as the recommendation or a named alternative), there is no implementation. Claude:

- Acknowledges the defer in plain text.
- Prints the revisit trigger (already present in the Draft entry for `open-questions.md` section of the emitted report).
- Does NOT write to `open-questions.md` — per the file-writes prohibition, the user copies the Q&lt;N&gt; block manually if they want formal tracking.
- Does NOT begin any other work.

### Implementation path when a non-Defer option is adopted

Treat the adoption as an implicit invocation of `/build <recommended-option-description>`. Follow `/build` semantics exactly: non-trivial work invokes `architect-review` DESIGN mode before coding, then `code-reviewer` on the diff, then specialist agents (`security-auditor`, `performance-engineer`, `test-automator`) per the standard `/build` trigger rules. Trivial work (single-file config tweak, doc edit) skips straight to implementation.

### Two-step authorization: adoption ≠ commit

**Adoption authorizes the work, not the ship.** Commits require a second, explicit authorization:

- After implementation completes, the user invokes `/ship` (or explicitly says `commit` / `commit and push`).
- A second `go` after implementation completes is NOT an adoption signal — the scope rule already closed the window when implementation started. Claude asks for commit intent explicitly.

This preserves Zaude's existing commit-step discipline: `/ship` runs the review chain, drafts the commit, and requires approval of the drafted message. `/decision-map` adoption cannot short-circuit that.

## Refusal outputs

### Empty `$ARGUMENTS`

```
Usage: /decision-map <question> [--revisit] [--force] [--draft-decision]

Flags:
  --revisit          Bypass the "already-settled" refusal. Question must include a rationale clause.
  --force            Bypass the "insufficient context" refusal. Confidence capped at low.
  --draft-decision   Include a print-only decisions.md entry block in the output.

Examples:
- /decision-map should we switch from Postgres to SQLite for the test harness?
- /decision-map --revisit should we keep the in-memory rate limiter? (revisit because we now have 3 dynos)
- /decision-map --force should we use gRPC or REST for the new internal service?
- /decision-map --draft-decision how should we structure the auth service — monolith or extracted?
```

### Product / process / people decision in disguise

```
This looks like a <product | process | people | timing | pricing> decision, not a technical one. `/decision-map` is scoped to technical decisions only: architecture, library choice, schema design, API shape, test strategy, refactor scope, dependency choice.

If there is a technical sub-question embedded in this decision, restate it as a technical question and I will analyze that.
```

### Already-settled without documented revisit trigger

```
This was decided in `decisions.md` on <date>:

> <verbatim excerpt of the relevant entry>

Before I re-analyze, tell me what changed — a new constraint, new information, or a concrete signal that the prior rationale no longer holds. If you want to override anyway, re-invoke as:

    /decision-map --revisit <question with the rationale for revisiting>
```

### Insufficient context

```
I don't have enough project context to analyze this well. Missing or empty:

- <name the specific missing pieces: spec.md, architecture.md, CLAUDE.md rule bearing on this question, neighboring precedent in decisions.md — whichever are absent>

Populate the missing vault files first (especially `spec.md` and `architecture.md`), then re-invoke.

If you knowingly want analysis against the thin vault, re-invoke as:

    /decision-map --force <question>

This bypasses the refusal and caps the recommendation's confidence at `low`. Every inference against missing context will be flagged as unsupported.
```

### Option space is empty under current constraints

```
Every option considered fails a hard rule in `CLAUDE.md` or `spec.md`:

- <option> fails <rule verbatim>
- <option> fails <rule verbatim>
- <option> fails <rule verbatim>

Two options:

1. Propose a different option that passes the hard rules.
2. Explicitly override one hard rule (e.g. "override the 'no mock data' rule for this test harness only") and re-invoke `/decision-map`.

I will not recommend an option that fails a hard rule without an explicit override.
```
