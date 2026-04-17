# Philosophy & best practices

This is the opinionated part of the docs. The rest of Zaude tells you **what** it does; this doc tells you **why** it does it that way, and what happens when you try to work around it.

Read it once. Come back to it when you feel the urge to skip `/wrap` or edit a past decision "just this once".

---

## The core split: hooks for enforcement, skills for suggestions

Zaude is built on one structural idea. Everything else flows from it.

**A hook is a Python or shell script the Claude Code harness runs automatically.** You cannot forget to invoke it. You cannot "mean well and skip it". The harness fires it, every time, whether you want it or not. Hooks live in `~/.claude/hooks/` and are registered in `~/.claude/settings.json`.

**A skill is a markdown file Claude reads when you invoke a slash command.** Skills tell Claude what to do. Claude may follow the instructions perfectly, or it may drift. The harness does not check.

This split is the single most important thing to internalize:

| Guarantee type | Put it in | Why |
|---|---|---|
| "This always happens" | Hook | Mechanical. No exceptions. |
| "This is the standard workflow" | Skill (slash command) | Documented. Claude usually follows it. |
| "This is a rule we've agreed on" | `03-patterns/*.md` or memory | Loaded into context. Claude sees it. May or may not comply. |

### What Zaude uses hooks for

- **Loading vault context.** `SessionStart` hook reads 6 core files + archives + session logs + patterns + memory. If Claude had to do this via a skill, it would sometimes forget a file, sometimes truncate, sometimes skip the memory directory. As a hook, it is deterministic.
- **Blocking frozen-zone writes.** `PreToolUse` on Edit/Write checks the file path against `frozen_zones`. Claude cannot write to a blocked path even if it thinks it should. The override requires plain-language confirmation from you, which re-invokes Claude with fresh context.
- **Auto-committing and pushing the vault.** `SessionEnd` hook runs after the conversation ends. Claude cannot "forget to push". The hook guarantees the vault state is durable within seconds of the session closing.

### What Zaude uses skills for

- **`/start`, `/build`, `/review`, `/ship`, `/wrap`.** These are instructions to Claude about what workflow to follow. Claude reads them, follows them most of the time, and the `/wrap` memory sweep persists corrections when it drifts.
- **Agent invocation.** The `/build` skill says "invoke `code-reviewer`, then `security-auditor` if applicable, then `architect-review`". Claude follows that sequence. If it skips one, your corrections during the session become memory rules that reinforce the pattern next time.

### Where people get confused

Newcomers sometimes ask: "why not just put the whole workflow in hooks?" Because hooks are the wrong tool for anything that requires judgment. `code-reviewer` needs to read the diff and think. That's a skill + agent, not a hook. Hooks are mechanical, fast, stupid — they are the right tool exactly when you need zero thinking and 100% reliability.

The inverse question ("why not put everything in skills, skills are easier to edit?") runs into the drift problem. A skill is a suggestion: Claude reads it, interprets it, and may skip parts under load. If you care about the outcome 100% of the time, drift is unacceptable. If 80% is good enough, a skill is fine.

### Decision matrix — is this a hook or a skill?

| Question | If yes, it's a... |
|---|---|
| Does it need to run on literally every session? | Hook |
| Is it a pure mechanical action (read file, commit, deny path)? | Hook |
| Does it need to block a tool call deterministically? | Hook |
| Does it need to think about the content of the code? | Skill + agent |
| Is it OK if Claude occasionally skips this? | Skill |
| Is this documentation of a workflow, not an enforcer of it? | Skill |
| Is this something the user sometimes overrides mid-session? | Skill |

### Example: "always run the tests before commit"

If you want a guarantee: add a `PreToolUse` hook that intercepts the Bash tool when the command matches `git commit`, runs `npm test`, and emits a deny decision if tests fail. Mechanical. Unforgettable.

If a suggestion is enough: add "run `npm test` before committing" to your project's `CLAUDE.md`. Claude will usually do it. Not always.

Pick based on how much you care.

### Example: "credentials never land in the vault"

This one *has* to be a hook — credentials in commits are uncorrectable after the fact. But the specific hook is tricky: Claude rarely writes credentials directly; it edits files that might then get opened and pasted into. A hook that greps every write for common credential patterns (`ghp_*`, `sk-*`, `-----BEGIN .* PRIVATE KEY-----`) + denies is the right shape. Zaude doesn't ship this hook yet (false-positive risk), but it's a natural extension — see [13-customization.md](./13-customization.md) for how to add it.

### Example: "every session ends with a code review"

A skill, because "review" requires judgment. But with a wrinkle: the `/wrap` skill has an explicit final step to run `code-reviewer`, and the SessionEnd hook (which does fire mechanically) commits whatever state the repo is in regardless. So the split is: review is a skill-level enforcement (in `/wrap`), and sync is a hook-level enforcement (SessionEnd). If you skip `/wrap`, the review doesn't happen but the sync still does. That's intentional — the sync is non-negotiable, the review depends on you invoking the ritual.

---

## Don't vibe code

**Vibe coding** is what happens when you let an AI produce code and you accept it because it *feels right*, without reviewing it, without tracking why you made the choice, without remembering what you shipped last week.

It looks like this:

- "Yeah, that looks good, ship it."
- "I don't remember why we did it that way — let me just redo it."
- "We'll write tests later."
- "I'll rotate that credential… probably."
- "I think we discussed this, but I can't find the thread."

It feels productive. The output looks fine. Sometimes it even works.

The problem is that vibe coding is a debt-accumulator. Each unreviewed commit adds risk. Each unrecorded decision means the next session starts cold. Each "fix later" becomes a long tail of latent bugs. Three months in, your codebase is a stack of plausible-looking patches held together by the hope that no one asks "why".

Zaude is structured specifically to prevent this by making the careful path the easy path:

| Vibe coding instinct | Zaude intervention |
|---|---|
| "Skip the review, it looks fine" | `/ship` runs the review chain whether you want it to or not. CRITICAL/HIGH findings hard-stop. |
| "I'll remember why we picked X" | `/wrap` appends to `decisions.md` every session. Append-only. Never edit. |
| "I don't need to log this session" | `/wrap` writes the session log, no opt-out short of skipping the command. |
| "The context from last week is in my head" | `SessionStart` hook loads the last 3 session logs + current-state.md automatically. |
| "I'll rotate that credential later" | `/wrap` lists exposed credentials at session end, first-4/last-4 only. Rotate now, not later. |
| "I'll modify that legacy file just this once" | `PreToolUse` frozen-guard denies the write. Override requires explicit plain-language confirmation. |

The goal is not to make you careful. The goal is to make carelessness hard.

### Why "structurally prevent" matters

Discipline-through-willpower breaks down at exactly the moments you most need it:

- **Tired at 9pm, one last push before bed.** You skip the review. Ship something broken.
- **Urgent bug, 15-minute fuse.** You edit a frozen file, forget to unfreeze, and now three adjacent tests break silently.
- **Friday afternoon, brain off.** You paste a token, use it, close the laptop. Forget to rotate.

Each of these happens *despite* knowing better. Zaude's design assumption: **knowing better is not enough.** The hooks fire regardless of your tiredness, the slash commands do the boring work regardless of your mood, the append-only logs capture decisions you'd otherwise rationalize after the fact.

That's the difference between "aspirational discipline" (what people tell themselves they'll do) and "mechanical discipline" (what actually happens). Zaude traffics in the second.

### What vibe coding costs at three months

Concrete failure modes that vibe-coded codebases reliably develop:

- **Orphaned abstractions.** Someone built a helper class six months ago for a reason nobody remembers. Nobody's willing to delete it. It survives every refactor.
- **Phantom dependencies.** An import that should be dead code still loads a 2MB library because deleting it broke something once and the fix was "just don't touch it".
- **Confident wrong answers from the AI.** When Claude doesn't have the project's history in context, it gives plausible-but-incompatible suggestions. You accept them because they sound right. They aren't.
- **Copy-paste monocultures.** Three functions that do almost the same thing with slight differences, because nobody remembered the first one existed.
- **Tests that pass because nothing is tested.** Coverage 80% in CI, but the 80% is all happy paths on the one service the original author cared about.

Zaude doesn't eliminate these but shortens the loop dramatically: the decision log, the append-only session trail, the memory rules, all make it harder to forget why something exists. Forgetting is the root cause of all of the above.

---

## Do's — embrace these

### Let the hook load context. Don't paste files.

When a session starts and you need Claude to know about `current-state.md`, the hook has already loaded it. Do not paste the file in. Do not ask Claude to read it. Just reference it by name — "per current-state.md…" — and Claude will find it in the injected context.

Why this matters:
- The hook loads the *whole* context atomically. If you paste pieces, you miss some.
- The hook's injection is prefixed with `=== VAULT CONTEXT FOR <project> ===`. Claude's skills know to trust that prefix.
- Every paste you do manually is a paste you will forget tomorrow. The whole point is that you do not have to remember.

### Use slash commands, not memorized phrases.

If the workflow is `/build`, do not type "plan this feature, have the right agents review it, then stop and wait for my approval before committing". That is the `/build` skill. Type `/build`.

Memorized phrases drift across sessions. Slash commands are versioned files on disk. If the workflow changes, you change the file once, not every future prompt.

### Append decisions immediately, not at end-of-week.

The moment you make an architectural call, `/build` or `/ship` will offer to append to `decisions.md`. Take it. Don't wait.

Why: week-old decisions are 80% reconstructed, 20% actual memory. The rationale you'd write Friday is not the rationale you had Monday. Append at the moment.

### Save feedback memory when corrected.

When Claude does something and you correct it — "no, don't do X, always do Y" — that is a memory-worthy event. At `/wrap`, the memory sweep catches these. You can also proactively tell Claude "remember that" and it will persist immediately.

Memory files live in `~/.claude/projects/<encoded-cwd>/memory/feedback_*.md`. They are loaded into context on every future session at the top, so the correction carries forward.

**Worked example — persisting a correction.** Mid-session:

```
You: stop using `any` in TypeScript. Use `unknown` and narrow.

Claude: Got it — will use `unknown` going forward. Want me to persist
this as a memory rule?

You: yes
```

Claude writes `~/.claude/projects/<encoded-cwd>/memory/feedback_no_any_type.md`:

```markdown
---
type: feedback
tags: [typescript, style]
created: 2026-04-17
---

# Rule: no `any` in TypeScript

When writing TypeScript:
- Use `unknown` for values of unclear shape and narrow with type guards
- Use `never` for unreachable branches
- Only use `any` if interacting with a library whose types are wrong
  AND file an open question to fix the types upstream

Triggered by: correction from 2026-04-17 on feedback persistence
```

Next session, the SessionStart hook loads this file. Claude sees it in context before you even ask. Behavior sticks.

### Run the review chain before commit, not after.

`/build` → review → fix → `/ship` is the correct sequence. Do not `/ship` and then run `/review`. The point of gating `/ship` on CRITICAL/HIGH is to prevent the bad commit from landing in the first place.

If you need a sanity check mid-feature, `/review` is read-only and you can invoke it anytime between `/build` and `/ship`.

### Invoke `architect-review` in DESIGN mode before coding.

Anti-pattern rule 3 says this; it's worth repeating because skipping it is the most common source of "we built it wrong and now it's expensive to fix". For any new service, route, middleware, schema table, or major component: ask `architect-review` what the right shape is *before* you write code. Then build it. Then run REVIEW mode after.

Running REVIEW only — after the code exists — catches structural issues, but fixing them means rewriting work you already did. The ratio is roughly 3–5x more effort than getting the shape right the first time.

### Ship small, ship often.

A session should produce one cohesive change, not a grab-bag of five unrelated fixes. Smaller ships mean:

- `/review` runs faster and gives clearer findings
- The decision log entries are specific, not "many things happened"
- Rollbacks are surgical, not archaeological
- Reviews are scoped — a reviewer finding in a small diff is obvious; in a 50-file diff it's noise

If you catch yourself with a 30-file uncommitted changeset, that's a signal to ship what's complete and start a new session for the rest.

### When Claude pushes back, listen.

Zaude's global `CLAUDE.md` instructs Claude to push back on bad ideas. When it does, take the pushback seriously before overriding. Often Claude is right — it just read the decision log and noticed your request contradicts a 2026-01-15 decision. Other times it's wrong, in which case tell it why and it will update its reasoning.

What to watch for:

- **"This contradicts decisions.md 2026-01-15."** Open that entry. Is the old decision still correct? If yes, drop the new plan. If no, append a reversal entry and proceed.
- **"Rule 7 says don't modify working code outside the task."** If the adjacent fix is genuinely in scope, pull it in explicitly. If not, file an open question.
- **"This looks like a credential."** Redact before proceeding. Always.

---

## Don'ts — these will quietly wreck the system

### Don't skip `/wrap` because "nothing important happened".

Sessions where "nothing happened" are exactly the sessions where something small slipped through unnoticed. `/wrap` does things no other command does:

- Final `code-reviewer` pass (catches uncommitted cruft)
- Memory sweep (catches corrections you made mid-session)
- Open-questions append (captures unresolved items)
- Credential scan (catches pasted tokens)
- Vault push (makes the day durable)

A "nothing happened" `/wrap` takes 20 seconds and costs nothing. Skipping it is a promise that next session's context will be incomplete.

### Don't edit past decision entries.

`decisions.md` is append-only. The rule is absolute. If you realize a past decision was wrong, write a new entry that references the old one and explains what changed:

```markdown
## 2026-04-20 — Revert decision on 2026-04-17 workspace routing

**Decision:** The 2026-04-17 entry chose /ws/:slug. After prototyping,
we are reversing to /workspaces/:slug for readability. The 2026-04-17
entry stays untouched.

**Rationale:** URLs get spoken aloud in onboarding. /ws reads as "dub-ess"
which nobody recognized. Length cost is trivial.

**Implications:** Three PRs need to be rebased. The future
bridge-drop question (Q13) still applies; just uses the new prefix.
```

Why append-only:
- Editing past entries loses the context of when and why the original decision was made.
- Future you will not remember *that* there was a revert, let alone *why*. The append is the reminder.
- Append-only files are trivially diffable. Edited files require archaeology.

### Don't commit credentials "temporarily".

There is no such thing as a temporary credential commit. Git preserves history. Every "I'll rotate it tomorrow and rewrite history" commit has, in practice, a 100% chance of being scraped by the time you get around to it.

The rule:
- Pasted credential → use it immediately, never write to a file.
- At `/wrap`, credential scan lists first-4/last-4 only.
- You rotate at the source (GitHub PAT page, cloud console, etc.).
- Never touch `git filter-repo` as a "safe cleanup" — once it's in history, treat as compromised.

See [03-patterns/credential-handling.md](../templates/vault/03-patterns/credential-handling.md) for the full rulebook. The hook cannot enforce this one — it's a discipline rule, not a mechanical one.

### Don't bypass frozen-guard without plain-language override.

The `PreToolUse` hook denies writes to paths in your `frozen_zones`. When it denies, Claude reports the block with the hook's reason text. The override is not a flag or a config toggle — it is you telling Claude in words that yes, this specific write is intentional.

Why this friction is deliberate:
- Frozen zones exist because past sessions caused harm by editing those paths.
- A silent bypass (edit config, retry, re-freeze) defeats the whole point.
- The plain-language override forces you to articulate why, which is the smallest possible audit log.

If you find yourself overriding the same zone frequently, the fix is to narrow the zone, not disable the guard.

### Don't treat session logs as an afterthought.

The session log is not a diary. It is the context your next session will read. If today's log says "worked on stuff, shipped it" you have wasted tomorrow's hour.

A good session log:

```markdown
# 2026-04-17 — Password reset flow shipped

## Summary
Added POST /api/auth/reset-request and POST /api/auth/reset-confirm.
HMAC-SHA256 tokens with 1-hour TTL, secret loaded from AUTH_RESET_SECRET.
Rate limited to 5/hour per IP on reset-request.

## Commits shipped
- `abc9999` — Add password reset flow with env secret + rate limiting

## Key decisions
- HMAC not JWT: simpler, scope is 100% internal (we control both sign
  and verify). Decision logged separately.

## Lessons / corrections
- Reviewer flagged hardcoded secret as CRITICAL. Corrected to env-loaded.
  New memory rule persisted: feedback_no_hardcoded_secrets.

## Credentials exposed
- Test SMTP password (test acct, ends in …9x1w). Rotated during session.
```

That log tells the next session what happened, why, what was learned, and what's safe. Six months from now, this is how you reconstruct the audit trail.

A bad session log, by contrast:

```markdown
# 2026-04-17

Worked on auth stuff. Shipped some fixes. All good.
```

Two months later, "auth stuff" is not a useful entry point. Which endpoints? Which fixes? What were the tradeoffs? You threw away the signal. The next session has to start over.

### Don't let `open-questions.md` grow silently.

`open-questions.md` is where unresolved questions land. It's useful only if you actually look at it and resolve or close questions over time. A 200-entry unresolved list is the same as no list — you stop reading it.

Good hygiene:

- `/wrap` appends new Q entries when they come up
- At session start, `/start` surfaces unresolved CRITICAL/HIGH questions
- When you resolve a question, mark it inline: `## Q7 — Title (SEVERITY) — RESOLVED 2026-04-17`
- Don't renumber. Don't delete. Resolution-in-place keeps the history visible.

If the unresolved list is creeping past 20, schedule a triage session specifically to close questions.

---

## The 7 anti-patterns — condensed

Full entries live in [03-patterns/anti-patterns.md](../templates/vault/03-patterns/anti-patterns.md). Quick reference:

### 1. Hooks for enforcement, skills for suggestions

Put never-fail logic in hooks. Workflow documentation in skills. If you catch yourself relying on a skill for something you called "always" or "never", it belongs in a hook.

→ [Full rule](../templates/vault/03-patterns/anti-patterns.md#rule-1--hooks-for-enforcement-skills-for-suggestions)

### 2. Use slash commands, not memorized phrases

Manual prompting is fallback. `/start`, `/build`, `/review`, `/ship`, `/wrap` exist so the review chain runs mechanically. Don't re-invent them each session.

→ [Full rule](../templates/vault/03-patterns/anti-patterns.md#rule-2--use-slash-commands-not-memorized-phrases)

### 3. Design before review, not after

For new services, routes, middleware, schemas, or major components: invoke `architect-review` in DESIGN mode *before* writing code. Run REVIEW mode after for coverage. Post-hoc structural fixes cost 3–5x more than upfront design.

→ [Full rule](../templates/vault/03-patterns/anti-patterns.md#rule-3--design-before-review-not-after)

### 4. Credentials pasted inline are ephemeral

Never write a full credential to any vault file, repo, or log. Show first-4 / last-4 when referencing. At `/wrap`, list them for rotation.

→ [Full rule](../templates/vault/03-patterns/anti-patterns.md#rule-4--credentials-pasted-inline-are-ephemeral)

### 5. No mock data, no placeholders, no hardcoded fallbacks

Every value from a real source. Empty state over fake data. Demo with a real record from dev, not a made-up one.

→ [Full rule](../templates/vault/03-patterns/anti-patterns.md#rule-5--no-mock-data-no-placeholders-no-hardcoded-fallbacks)

### 6. Root-cause-first remediation

Diagnose the actual cause before patching. If the root cause is bigger than your time budget, ship the symptomatic patch **and** file an open question describing the real fix. "It works now" without knowing why is a failure.

→ [Full rule](../templates/vault/03-patterns/anti-patterns.md#rule-6--root-cause-first-remediation)

### 7. Don't modify working code outside the task

Only touch files the task needs. Adjacent problems get mentioned in the report, not silently fixed. If the fix belongs in this PR, add it to scope explicitly and mention it in the commit message.

→ [Full rule](../templates/vault/03-patterns/anti-patterns.md#rule-7--dont-modify-working-code-outside-the-task)

---

## On pushback

Claude is not supposed to be a compliant tool. The global `CLAUDE.md` explicitly says:

> You are not a compliant tool. You are expected to think.

When you ask for something that contradicts a project rule, a past decision, or common sense, Claude should push back. If it doesn't, that's a bug in the instructions, not a feature. Fix it by:

1. Correcting Claude in the moment ("no, don't silently comply — this violates rule 7").
2. Letting the `/wrap` memory sweep persist that correction.
3. Next session, Claude sees the memory rule and pushes back earlier.

The pattern compounds. After a few weeks, Claude is catching things before you even notice them. That compounding is the whole value proposition — it only works if you actually correct in the moment instead of sighing and accepting.

---

## On destructive actions

If you run Claude Code with `--dangerously-skip-permissions`, there are no confirmation prompts. The replacement is an **announcement pattern**:

```
⚠️  DESTRUCTIVE ACTION INCOMING
Action:   [what, one sentence]
Risk:     [what could go wrong]
Rollback: [how to undo]
Proceeding in one beat...
```

Then Claude acts after one beat. You can Ctrl+C during the beat if wrong.

The announcement is not optional. It is the replacement for the prompt. If you notice Claude doing destructive things silently, correct in the moment and persist as a memory rule.

Full list of things that require announcement lives in the global `CLAUDE.md` template.

---

## On discipline vs velocity

Some days Zaude feels like friction. `/start` reports, `/build` plans, `/review` nitpicks, `/ship` gates, `/wrap` sweeps. That's five commands before you ship a one-line fix.

Two answers:

**Short answer:** for a one-line fix, you can skip `/build` and just edit. Type `/review` before `/ship`. That's it. Zaude does not demand ceremony for trivial changes; it demands discipline for production-shape changes.

**Long answer:** velocity without discipline is a mirage. The first month of vibe coding produces more visible commits. Month three you're rewriting things because you don't remember why they are shaped the way they are. Month six you can't ship because the uncovered edges pile up faster than you can patch them. Zaude's overhead is front-loaded; the velocity payoff is compounding.

The data is anecdotal but consistent: projects that adopt Zaude spend about 20% more time per session in the first two weeks, then reach sustainable ship-rate that Vibe Coding never does.

### The "what's the minimum ceremony" decision tree

Not every change warrants the full `/build` → `/review` → `/ship` → `/wrap` ritual. Rough guide:

```
Change scope?
├── Typo / copy-edit / one-line CSS tweak
│     → edit directly, /ship, skip /wrap if nothing else happened this session
├── Bugfix, single function, clear root cause
│     → edit directly, /review, /ship, /wrap
├── New feature, touches 2+ files
│     → /build (full chain), /ship, /wrap
└── Architectural change, new service, schema migration
      → /build with explicit DESIGN invocation, /ship, /wrap,
        and append a decisions.md entry
```

The ritual scales with the blast radius of the change. Don't use a sledgehammer on a finishing nail; don't use a tack hammer on a foundation.

---

## Common objections, answered

### "This is just ceremony. I ship fine without it."

Maybe. Some engineers are extraordinarily disciplined without external scaffolding. Most aren't. The honest question is not "do I need Zaude" but "will my discipline survive a bad week". If you've ever lost a weekend to a bug that turned out to be a credential you forgot to rotate, or spent an afternoon re-explaining context to Claude because you didn't keep notes, Zaude removes that whole category of failure.

### "I already have CLAUDE.md. Isn't that enough?"

CLAUDE.md is a document. Zaude is a mechanism. The difference matters when Claude is under token pressure and starts summarizing — documents can be paraphrased away, mechanisms can't. The CLAUDE.md at the top of the Zaude template is there, but it's reinforced by hooks that load it, commands that reference it, and a vault that makes past decisions first-class.

### "The review chain slows me down."

It does, by design. The tradeoff is: slower per-commit, faster per-month. The time you spend on review is time you don't spend debugging production incidents. It is also time you don't spend re-reading your own code next week trying to figure out if it's safe to change. Review adds net velocity on any project lasting longer than three weeks.

### "I don't want to commit my vault to GitHub."

You don't have to. The vault is a local directory; the git integration is optional. If you skip the SessionEnd sync or keep the repo local-only, Zaude still works. You just lose cross-machine portability and the audit trail on GitHub. Most teams find those worth the privacy tradeoff (private repos are cheap); a few don't.

### "My project is a prototype. None of this matters."

True until it's not. The usual trajectory for "just a prototype" is: three weeks in it's still alive, three months in it's in production, six months in it has users. At which point you wish you'd been tracking decisions from day one. If you're absolutely certain the project dies in a weekend, skip Zaude. Otherwise, the install takes 10 minutes and the habit takes a week to form.

### "I'm not going to read a 600-line philosophy doc."

Then read this box:

> Hooks enforce. Skills suggest. Decisions are append-only. Credentials are ephemeral. `/wrap` every session.

That's the whole thing. The rest is context for when you catch yourself disagreeing.

---

## On forking vs customizing

If your customizations are specific to you (team conventions, company-specific frozen zones, private pattern files), just edit your local copy. Don't fork.

If your customizations are generally useful (a new pattern file for "Django + Postgres projects", a better hook that auto-formats on write, a `/test` command), **please** open a PR on the Zaude repo. That's how the framework improves.

The rough test: if someone else would want it, upstream it. Otherwise keep it local. See [13-customization.md](./13-customization.md) for the how.

---

## The short version

If you take one thing away:

> **Hooks enforce. Skills suggest. Discipline is mechanical, not aspirational.**

Everything else — every `/wrap`, every append-only decision, every credential scan — is Zaude making it easier to do the right thing than the wrong thing. That is the job. Trust the friction.

---

## See also

- [03-architecture.md](./03-architecture.md) — the hook/skill split in diagrams
- [06-hooks.md](./06-hooks.md) — hook contracts and internals
- [03-patterns/anti-patterns.md](../templates/vault/03-patterns/anti-patterns.md) — the full 7 rules
- [03-patterns/credential-handling.md](../templates/vault/03-patterns/credential-handling.md) — credential discipline
- [10-workflow.md](./10-workflow.md) — what a session looks like end to end

## What's next

After you've internalized the philosophy, the most valuable thing to read is [13-customization.md](./13-customization.md) — that's where you decide what rules apply to your team and codify them as hooks, patterns, or commands.
