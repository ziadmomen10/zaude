# Zaude 2.0 — the engine (preview, on the `v2` branch)

Zaude 2.0 reimplements the three Zaude promises (persistent memory, durable workflow, production
discipline) as a **deterministic Python kernel** that gates Claude Code's tools — so process can't
be skipped, not just suggested.

## What's here
- **Enforcement kernel** — a workflow state machine + tamper-evident (hash-chained + HMAC) trace;
  `state.json` is a rebuildable projection. Risk-scaled gates: trivial work flows, risky work is gated.
- **Risk-tier fast lane** — small changes ship in 2 commands; the no-broken-ship evidence gate stays.
- **GitHub Projects PM layer** — Intake column + promote → Feature(user-story/tasks/bugs), synced
  to the signed trace + vault + memory; bidirectional with a conflict model.
- **Generator** — slash-commands + agents + the hook block rendered from one `policy.json`.
- **Portable installer + updater** — bootstrap on any PC, `zaude update`, fully reversible.

## Try it (isolated; does not touch your existing Zaude)
```bash
bash v2/install.sh                                   # lays the kernel into ~/.zaude
python "$HOME/.zaude/bin/zaude.py" gen               # generate the /z* commands + agents
python "$HOME/.zaude/bin/zaude.py" install --yes     # optional: wire into ~/.claude (z-prefixed)
```
codex-reviewed; 38 kernel tests; the PAT lives only in `~/.zaude/secrets` (never committed).
