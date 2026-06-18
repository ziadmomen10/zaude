# 17 — Agent ecosystem: which agents Zaude recommends, and why

_Market scan: 2026-06-18. Re-run periodically — the ecosystem moves fast and the top packs ship from `main` without versioned releases._

Zaude's `/build` and review chains depend on **capability agents** Zaude does **not** generate (they live in `~/.claude/agents/`). `zaude agents` reports which required ones are installed vs missing, and — after this refresh — points each missing one at a **vetted, ranked source**. Zaude never auto-installs them: every community pack is written for someone else's stack, so adoption stays a human decision (*read the prompt, check the tool list, pin a commit, rewrite before trusting*).

## The decision that didn't need changing: the harness pairing

The most important "agent" choice is the **harness + model**, not a markdown subagent pack. On the 2026 public benchmarks:

| Benchmark | #1 | #2 |
|---|---|---|
| Terminal-Bench 2.1 | **Codex CLI + GPT-5.5 — 83.4%** | Claude Code + Opus 4.8 — 78.9% |
| SWE-bench Pro | **Claude Opus 4.8 — 69.2%** | GPT-5.5, Gemini 3.1 Pro behind |

Zaude's review panel runs **Claude (Opus 4.8)** lenses and pairs them with **best-effort Codex (GPT-5.5)** — the two leading agentic harnesses, each #1 on a different benchmark — plus a **third best-effort seat, OpenCode**. That design is the benchmark-best combination available in 2026; the market scan **validated** it rather than replacing it. (All external seats stay best-effort and never gate — see the graceful-codex design; absence is recorded honestly and the cycle continues on Claude lenses alone.)

### The three review-panel seats

| Seat | Harness / model | Role | Gates? |
|---|---|---|---|
| `claude_lenses` | Claude Opus 4.8 (#1 SWE-bench Pro) | always-on reviewer | the lenses produce the findings, but the ship gate reads only `unresolved_critical_high` |
| `codex` | Codex CLI / GPT-5.5 (#1 Terminal-Bench) | best-effort second opinion | **never** |
| `opencode` | OpenCode (172K★ OSS, **provider-agnostic**) | best-effort, **model-diverse** third voice (Gemini / GPT / local) | **never** |

OpenCode earns the third seat precisely because it is **provider-agnostic**: it can run a *different model family* than Claude or Codex, so the panel gets genuine model diversity rather than a third Claude/GPT echo. Each external seat is independent — one's no-credit backoff never affects the other — and the kernel records each honestly (`zaude opencode` / `zaude codex` show availability + retry window). The driver runs it headless (`opencode run --model <provider/model> "<prompt>"`) and reports the verdict via `zaude review --opencode-verdict pass|concerns|fail`; **a missing / unauthenticated / out-of-credit / crashed OpenCode never blocks `/review` or `/ship`.**

## Subagent packs: no single winner → a ranked, caveated catalog

There is no one "best" pack, so `zaude agents` ranks vetted sources with their real tradeoffs:

1. **`wshobson/agents`** — broadest (192 agents / 156 skills / 16 orchestrators, ~36.6K★). Ships native to Claude Code **and Codex CLI**, Cursor, Gemini CLI, OpenCode, Copilot from one Markdown source.
   _Caveat:_ single-maintainer and **no versioned releases** — you track `main`, so **pin a commit** for reproducibility.
   - Claude: `/plugin marketplace add wshobson/agents` → `/plugin install <plugin>`
   - Codex: `npx codex-marketplace add wshobson/agents`
2. **`VoltAgent/awesome-claude-code-subagents`** — community-maintained (lower single-maintainer risk); every agent declares a **minimal `tools` field** (least privilege). 100+, Claude-focused but multi-harness compatible.
3. **`VoltAgent/awesome-agent-skills`** — 1000+ agent **skills** from official dev teams + community; complementary to the subagent packs above.

### Role → upstream slug (primary source)

Zaude's role names differ slightly from upstream slugs; install and alias as needed.

| Zaude role | Used in | `wshobson/agents` slug |
|---|---|---|
| `code-reviewer` | review panel | `code-reviewer` |
| `architect-review` | review panel | `architect-reviewer` |
| `security-auditor` | review panel | `security-auditor` |
| `workflow-orchestrator` | `/build` | `context-manager` |
| `backend-developer` | `/build` | `backend-architect` |
| `frontend-developer` | `/build` | `frontend-developer` |
| `design-bridge` | `/build` | `ui-ux-designer` |

## What stays advisory

A missing agent **never** fails the cycle or changes an exit code — a fresh machine legitimately has none, and the review panel degrades gracefully (Claude lenses always run; Codex is best-effort). The refresh only makes the gap **actionable**: sourced, ranked, with the least-privilege and pin-a-commit caveats surfaced.

## Adjacent landscape (noted for completeness)

**OpenCode** (most-starred OSS agent harness, 172K★) is now the panel's **third best-effort seat** (above) rather than a subagent pack — adopted for its provider-agnostic model diversity. **Antigravity 2.0** (Google, May 2026) is another harness and a candidate for a *fourth* seat if a fourth model family is ever wanted; the seat machinery (`lib/opencode.py` mirroring `lib/codex.py`) generalizes to it. `ClaudeFast Code Kit` packages pre-tested hooks for teams that want an assembled kit rather than raw packs.
