# 16 — The Operator-Learning Layer (Persona + Collective Memory)

> Status: **Persona v1 shipped** (this doc). Collective-memory index, agent refresh, and vault
> upgrade are designed here and on the roadmap. Co-architected + reviewed with **codex**.

## Why
Zaude is the layer **on top of Claude Code** that makes development easier with fewer errors and
less effort (the C++-on-C thesis). The deepest lever is for autonomous work to **decide the way the
operator would** — not from a generic default, but from their *recorded* decisions.

## The model (2026 agent-memory standard — CoALA)
Memory splits three ways, and Zaude already had the raw material for each:

| Type | What | In Zaude |
|---|---|---|
| **Episodic** | what happened | the signed **trace** + session logs |
| **Semantic** | facts + **preferences** = the *persona* | `feedback_*` memory + the persona profile |
| **Procedural** | learned rules/workflows | `decisions.md`, project patterns, the persona's rules |

The **persona** is the distilled semantic+procedural profile, loaded **first** in autonomous mode.

## The hard part: *manage*, not just write+read
2026 research is blunt: *an agent that remembers everything remembers nothing useful.* Most systems
nail write+read and neglect **manage**. Persona v1 is deterministic about management:

- **Signals** — cheap, append-only observations the driver records as it notices the operator
  **correct / accept / reject / state a rule**. Byte-bounded log (never loads a pathological file).
- **Tiered promotion** — a belief is **tentative** until reinforced `PROMOTE_MIN` times; only
  **confirmed** beliefs enter the brief. *Repetition is how a real preference proves itself* — this
  is what keeps noise out.
- **Decay** — `confidence = strength × recency`. Strength `= r/(r+1)` (grows, never saturates);
  recency decays (Ebbinghaus-ish) but is **floored** so a reinforced belief never silently vanishes.
- **Drift** — a new statement *similar but not a match* to a confirmed same-category belief is
  flagged as **possible drift** (a cheap token heuristic — surfaced for the operator, not asserted
  as contradiction). Preferences evolve; don't silently overwrite.
- **Bounded** — per-category belief cap (on read *and* write), provenance cap, signal byte-cap.
- **Robust** — a corrupted-but-valid-JSON profile is sanitized on load and **never raises** (it's
  loaded first in autonomous mode — it must not crash the driver).
- **Private** — operator-private under `.zaude/persona/` (gitignored, `0700/0600`, never pushed);
  **every persisted string is secret-redacted in the kernel** — privacy is enforced, not a comment.

Kernel/driver split (same as the codex seat): the **kernel** owns the deterministic store + policy;
the **driver (LLM)** does the semantic distillation (records signals, promotes beliefs).

## Using it
```
zaude persona                                   # the 'decide as the operator would' brief
zaude persona --observe "<learned>" --kind correction|acceptance|rejection|stated_rule
zaude persona --promote "<belief>"  --category preference|rule|risk_posture
zaude persona --forget <id>
```
Autonomous mode (`CLAUDE.md`): load `zaude persona` first; record signals as you learn; promote
confirmed preferences; surface drift. Advisory — it informs judgment, never overrides an explicit
instruction or a safety gate.

## Roadmap (designed, researched — next builds)
1. **Collective-memory index** — semantic retrieval over the `feedback_*`/`project_*` memory files
   (start file-based; graduate to a vector/graph engine — Mem0 / Zep-Graphiti / Letta-tiering — if it earns it).
2. **Agent refresh** — adopt a multi-harness marketplace (e.g. **wshobson/agents**, which natively
   spans Claude **and Codex**), pinned + checked via `zaude agents`.
3. **Vault upgrade** — trace-anchored entries (every durable note links to an event id); the
   cross-project pattern library as the compounding asset.
4. **Fail-closed + waiver hardening** (codex's top architecture risks).

## References
Mem0 *State of AI Agent Memory 2026*; PersonaMem-v2; Letta/MemGPT tiered memory; the CoALA
episodic/semantic/procedural model; 2026 consolidation/forgetting (Ebbinghaus decay, LRU/LFU,
reflection).
