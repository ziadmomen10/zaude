# 15 · The Zaude 2.0 engine

Zaude 1 (chapters 01–14) is a set of hooks, slash commands, and vault conventions that *layer on*
Claude Code. Zaude 2.0 keeps all of that and adds an **engine**: a deterministic Python kernel that
gates Claude Code's tools so the workflow is *enforced*, not merely honored. This chapter explains
the engine. It lives in `kernel/` + `bin/` + `policy.json`; it installs into `~/.zaude/`.

## The thesis, finished

Zaude 1's rule was **hooks enforce, skills suggest — if it matters, it's in a hook.** A slash
command, though, can still be skipped ("just ship it" → no review). Zaude 2.0 turns the *whole
workflow* into a hook-enforced state machine: the LLM may *request* a tool; a `PreToolUse` hook
decides whether it's allowed based on where the work is in its lifecycle.

## Pieces

### Workflow state machine
`Intake → Clarified → Prioritized → Planned → Designed → RiskClassified → Approved → Implemented →
Tested → Reviewed → Verified → Shippable → Released → Closed`. Each transition is COMMITTED by a
slash command (`/zclarify`, `/zdesign`, `/zapprove`, …); agents only draft the content. A command
refuses if the input state is wrong or the required artifact is missing.

### Tamper-evident trace (the source of truth)
`.zaude/trace.jsonl` is append-only. Every row carries a sequence number, the SHA-256 hash of the
previous row, and an HMAC keyed by a per-project key stored **outside the repo** (`~/.zaude/keys/`).
A hand-appended forged transition (e.g. faking "Approved") breaks the chain and **fails closed**.
`state.json` is a *projection* rebuilt from the trace — `zaude repair` rebuilds it, `zaude
trace-verify` validates the chain + MAC + legal replay. If the conversation summary disagrees with
the trace, the **trace wins**.

### Risk-scaled gates (light by default)
The kernel keeps a small set of load-bearing gates and lets everything else flow:

- **design-before-impl** — blocks source edits before design+approval **only for T3/T4** (auth,
  migrations, prod, security, destructive). Low/unclassified work codes freely.
- **deploy-needs-release-token** — deploy/publish commands are blocked until `/zship` issues a
  token (which it only does after a clean review + verification).
- **protect-`.zaude`** — no tool may edit the kernel's own trace/state (never waivable).
- **evidence** — `fast-ship` and `/zship` refuse if tests didn't pass.

Bypassing a gate requires an explicit, logged `/zwaive` (lifecycle-state protection excepted). The
default project mode is **shadow** (logs would-deny, blocks nothing) until you promote to **enforce**.

### Risk-tier fast lane
For small/low-risk work, `/zfast` auto-completes Intake→Approved in one command (the full chain is
still recorded in the trace), and `/zfast-ship` does Approved→Released in one — but **refuses to
ship if the tests didn't pass**. Twelve steps collapse to two; the safety gate stays.

### GitHub Projects v2 PM layer
`/zintake` drops an idea in your **Intake** column. `/zpromote` turns it into a Feature (user story
+ acceptance criteria + child tech-tasks/bugs, distinguished by `type:` labels) and moves it to
Backlog. The board is a projection of the signed trace; `/zpm-sync` pushes, `/zpm-pull` reconciles
your GitHub edits back (PM-wins for business fields; both-changed → recorded conflict), `/zpm-mirror`
writes `vault/<slug>/backlog.md` + the memory index. The PAT lives only in `~/.zaude/secrets`.

### Config-driven generator
One `policy.json` is the canonical config. `zaude gen` renders the slash commands, the capability
agents (`evidence-verifier`, `supply-chain-auditor`), and the `PreToolUse` hook block into a staging
dir. `zaude install --yes` wires them into `~/.claude` under a `z` prefix (so they don't clobber
your existing `/start`/`/ship`), snapshotting first; `zaude uninstall` reverses it from a manifest.

## Install, update, uninstall

```bash
git clone https://github.com/ziadmomen10/zaude
bash zaude/install-zaude2.sh            # lay the kernel into ~/.zaude, generate
python ~/.zaude/bin/zaude.py install --yes      # wire /z* commands + the fail-open hook into ~/.claude
python ~/.zaude/bin/zaude.py update --source https://github.com/ziadmomen10/zaude   # later
python ~/.zaude/bin/zaude.py uninstall          # clean removal (snapshots first)
```

`install` only overwrites Zaude-owned files (else `--force`), never wipes your existing hooks (it
aborts on an unparseable `settings.json`), and the hook is **fail-open** — a project without a
`.zaude/` marker is untouched. `update` rejects credential-bearing URLs, validates the source, and
snapshots before overwriting. Everything is reversible via `~/.zaude/restore-points/`.

## Command reference (generated, `z`-prefixed)

Lifecycle: `zstart zclarify zprioritize zplan zdesign zclassify-risk zapprove zimplement ztest
zreview zverify zshippable zship zclose` · Fast lane: `zfast zfast-ship` · Control: `zstatus
zdoctor zrepair ztrace-verify zdod zwaive` · PM: `zintake zpromote zboard zpm-init zpm-sync zpm-pull
zpm-mirror`.

## Relationship to Zaude 1

The engine doesn't replace the vault, the memory system, or the agent roster — it enforces the
workflow around them. You can run the Zaude 1 conventions (chapters 04–14) alongside the 2.0 engine;
the kernel adds the deterministic spine that makes "just ship it" impossible.
