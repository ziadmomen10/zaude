# 18 — Threat model: what Zaude defends, and what it doesn't

_Added after a whole-architecture review (Claude + Codex, 2026-06-18). Codex's #1 finding was that several mechanisms "sound stronger than they are because the assumed attacker varies by paragraph." This document fixes the frame: it states the attacker/failure classes once, and for each says what is defended, by which mechanism, and what residual risk remains._

## The one-paragraph frame

Zaude is an **honesty-and-safety harness for an AI coding agent you are supervising**, not a sandbox and not a defense against a hostile human with shell access. Its job is to make **accidental agent mistakes** and **silent drift** loud and hard, to keep an **append-only, tamper-evident audit** of what happened, and to fail safe when its own integrity is in doubt. It deliberately gives the operator escape hatches. Everything below is scoped against *that* purpose.

## Trust boundaries

- **Inside the trust boundary:** the operator (you), the `~/.zaude/` kernel files, the per-project HMAC key (which lives **outside** the repo at `~/.zaude/keys/`).
- **Partially trusted:** the **agent** (Claude Code) — trusted to do useful work, *not* trusted to be correct or un-prompt-injected. This is the primary thing Zaude guards against, and it guards it best when the agent works through the file tools (`Edit`/`Write`/`MultiEdit`). **Caveat:** an agent with *unrestricted same-user `Bash`* has, technically, the same capability as a shell-access human (#4) — it can read the key and bypass tool-level gating. Zaude treats intentional human bypass as out of scope; it treats unrestricted agent Bash as a **known high-risk escape** that tool-level gates cannot robustly contain, mitigated by the always-on signed audit and the state-machine boundary, not eliminated.
- **Outside the boundary:** anyone with arbitrary shell access as your user. Zaude does **not** try to stop them — they can set `ZAUDE_DISABLE=1`, delete `.zaude/`, or read the key. Defending that is the OS's job, not Zaude's.

## The matrix

| # | Attacker / failure | Assumed? | Defended by | Residual risk |
|---|---|---|---|---|
| 1 | **Accidental agent mistake** (wrong file, skipped step, premature ship) | **Primary** | risk-tiered gates (`design_before_impl`, deploy-token), the validating reducer (illegal lifecycle transition → fail closed), the full signed audit trail | low — this is the case the design targets |
| 2 | **Prompt-injected / off-rails agent editing files via the `Edit`/`Write`/`MultiEdit` tools** (no key access) | **Yes** | `.zaude/` integrity is verified at **read** time (HMAC + hash-chain) — a hand-edited trace/marker fails closed; the HMAC **key is outside the repo**, so an agent confined to the repo files and these tools cannot forge a valid MAC; source edits are gated at T3/T4 | a marker *replaced* with valid non-matching JSON reads as "not ours" → fail open (≈ deleting `.zaude/`, #4); see #3 for the Bash escape |
| 3 | **Agent with unrestricted `Bash`** | Partially — and honestly **weakly** | the **signed audit still records the lifecycle**; the **real boundary is the state machine** (no release token without the review→verify chain), not any read-time check | **GAP (finding A):** a `Bash` `echo>file` / `sed -i` evades `design_before_impl` (the hook matches only `Edit\|Write\|MultiEdit`), and the deploy gate is a **regex tripwire** (bypassable via `sh -c "$CMD"` / aliases / `make deploy`). Worse, unrestricted same-user Bash can **read the HMAC key** (`~/.zaude/keys/`) and recompute a valid chain — so for this attacker the trace is **not robustly tamper-evident**. Unrestricted agent Bash therefore approaches the power of the out-of-scope shell-access human (#4); it is a known high-risk escape from tool-level gating, not a boundary Zaude can contain. Closing finding A narrows the *accidental* Bash case; it does not turn Bash into a real boundary. |
| 4 | **Operator intentionally bypassing Zaude** | **No — out of scope** | n/a (by design) | `ZAUDE_DISABLE=1`, `~/.zaude/disabled`, deleting `.zaude/`, `git`-level edits are all *intended* escapes. Zaude is a seatbelt, not a lock. |
| 5 | **Lost / deleted HMAC key** | Yes | if MACs exist but the key is gone, read fails **closed** (`TraceForged`) rather than silently downgrading; the SHA-256 **hash chain** still catches *inconsistent / unsophisticated* edits to a hash-only trace | the hash chain alone is **not** a forgery boundary — anyone who knows the row format can recompute consistent `prev` hashes (that is precisely why the MAC exists). The chain is integrity-against-accident; the MAC is integrity-against-a-knowledgeable-rewriter. A full rewrite by someone with the key (i.e. shell access, #4) is out of scope |
| 6 | **Corrupted / forged trace** | Yes | `read_trace(verify=True)` raises; the hook denies in **enforce** mode, allows in **shadow** (mode is itself signed) | a torn *tail* is healed (last partial line dropped) — by design, not corruption |
| 7 | **Corrupted / tampered project marker** (`.zaude/project.json`) | Yes | tri-state `resolve()` → a present-but-unreadable/garbled marker fails **closed** (PR #11); a parseable-but-mismatched marker (fresh clone, schema drift) stays fail-**open** | a marker replaced with valid JSON `{}` reads as "not ours" → fail open (equivalent to deleting `.zaude/`, #4) |
| 8 | **GitHub board / vault / memory drift** | Yes | they are **projections** of the signed trace, regenerable at will; PM edits reconcile back via `pm-pull` (PM-wins for business fields only); `vault-sync` re-derives from the trace | the projections are not themselves signed (they're derived); trust the trace, not the projection |
| 9 | **Generated surface drift** (slash-commands / agents / hook in `~/.claude`) | Yes | the generator writes to a **staging** dir with a per-file + per-policy SHA manifest; `install` applies with a snapshot; name regex blocks path-escape stems | manual edits to `~/.claude` after install aren't continuously reconciled |
| 10 | **Secret exposure** in side files / logs | Yes | persona/memory/codex/opencode strings are **redacted** in the kernel; the codex token and HMAC key are **never logged** (only labels); persona/memory are gitignored `0700/0600` and never pushed | redaction is regex-based (length-floored) — exotic secret formats may slip; treat the local machine as trusted (#4) |

## Fail-open vs fail-closed — the rule

- **No Zaude project here** → fail **open** (Zaude isn't managing this dir; never get in the way). Correct.
- **Onboarded, but integrity in doubt** (forged trace in enforce, *unreadable/garbled* marker) → fail **closed**. Correct. (A *valid* marker naming a different root — a fresh clone — stays fail-**open**, distinct from a corrupt one.)
- **Onboarded, shadow mode** → observe, never block. Correct.
- **Unexpected internal error in the hook/gate** → currently fails **open** (finding G). Defensible for "never brick the editor," but for an enforcement tool an *onboarded enforce* project arguably should fail closed on a gate-evaluation exception (distinct from a hook-transport failure). Open design question.

## Honest scope of the enforcement claims

- "Gate" language for the **deploy** check overstates it: it is a **heuristic tripwire**, not a boundary. The boundary is the state machine + the release token.
- `policy.json` is the **canonical config for the generated surface** (commands/agents/hook), **not** for the runtime gates/tiers/lifecycle, which are hardcoded in Python (only `required_agents` is drift-locked by a test).
- Lifecycle **evidence** (`/test --exit 0`, `/verify --built ok`) is a **driver-supplied attestation**, not a kernel-run measurement — the kernel cannot run your tests. The `evidence-verifier` agent is advisory.
- The **`protect_vault_projection`** gate (no hand-editing `vault/<slug>/current-state.md` / `decisions.md`) is a **tripwire over the file-editing tools** (Edit/Write/MultiEdit/NotebookEdit), targeting the #1 accidental path — a v1 command or agent hand-editing a file the kernel regenerates. It does **not** cover a Bash write to those files, and (like `protect_zaude`) a **relative** `file_path` resolves against the process CWD, not the project root, so it is out of scope. This is acceptable because the projection is **regenerable**: the next `zaude vault-sync` overwrites any stray edit from the signed trace. The trace itself (not the projection) is the protected source of truth.

These are not bugs; they are the true shape of a thin, stdlib-only harness. They are written down here so the README and command messages can match them rather than imply more.
