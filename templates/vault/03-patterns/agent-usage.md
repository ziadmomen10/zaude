# Agent Usage Rules

Conventions for when to invoke which agent. Loaded by the `SessionStart` hook on every session.

---

## Always-invoke agents (no exceptions)

These run mechanically via the `/build`, `/review`, and `/ship` commands. You don't pick them case-by-case — the skill triggers them.

| Agent | When it runs | Why it's non-negotiable |
|---|---|---|
| **`code-reviewer`** | Any diff (via `/review`, `/build`, `/ship`, `/wrap`) | Catches regressions, style drift, missed test coverage |
| **`architect-review`** (REVIEW mode) | Any structural change — new service, route, middleware, schema table, major component | Catches boundary / cohesion / error-handling issues before they compound |
| **`security-auditor`** | Any diff touching auth, JWT, passwords, encryption, credential storage, SSH operations, input validation | Catches classes of issue code-reviewer misses (rate limiting, token scoping, CORS, injection) |

If `/build` or `/review` don't invoke these automatically, something is wrong with the skill. Report it.

---

## Design-mode agents (run BEFORE writing code)

| Agent | Trigger | What it produces |
|---|---|---|
| **`architect-review`** (DESIGN mode) | New service, route, middleware, schema, component | Designed pattern Claude then implements |
| **`workflow-orchestrator`** | Start of `/build` | Decomposed ordered steps |
| **`design-bridge`** | Start of any frontend `/build` | Current `DESIGN.md` rules relevant to this feature |
| **`backend-developer`** | Backend `/build` after orchestrator | API shape, service layer, schema, error semantics |
| **`frontend-developer`** | Frontend `/build` after design-bridge | Component names, props, file paths, class recipes |

---

## Task-match agents (invoke when the task fits)

Only when the specific technology or concern applies.

- **`typescript-pro`** — complex TypeScript type puzzles, generics, conditional types
- **`javascript-pro`** — non-trivial async / event-loop / performance work in JS
- **`performance-engineer`** — when latency, memory, throughput becomes a goal
- **`test-automator`** — when building out a test suite from scratch, or debugging flaky tests
- **`cloud-architect`** / **`hybrid-cloud-architect`** — multi-cloud infrastructure design
- **`kubernetes-architect`** — K8s cluster design, GitOps, service mesh
- **`network-engineer`** — connectivity, TLS, CDN, load balancing
- **`terraform-specialist`** — IaC, state management, module design
- **`deployment-engineer`** — CI/CD pipelines, GitHub Actions, ArgoCD
- **`service-mesh-expert`** — Istio, Linkerd

### Mechanical triggers (v0.5+ VoltAgent specialists)

These 11 specialists use strict path/content/signal triggers — no judgment. The left column lists the agent, the right lists the exact condition under which it fires. Every rule includes an explicit `UNLESS` clause to prevent over-firing.

Read-only variants (`<agent>-readonly`) are used by `/microscope`, `/e2e-test`, `/decision-map`, and `/review`/`/ship`/`/wrap` review chains. Write-capable variants are used only by `/build`'s implementation phase.

| Agent | Fires when | Unless |
|---|---|---|
| **`debugger`** | User says `debug` / `diagnose` / `root cause` / `investigate failure`, OR scrollback contains a stack trace / error log / failing test output | Diff is a single-file change of ≤5 lines AND scrollback already names the exact line to fix |
| **`postgres-pro`** | Diff touches `*.sql`, `**/migrations/**`, `postgresql.conf`, OR request contains `postgres` / `psql` / `pg_` / `JSONB` / `vacuum` / `WAL` / `PITR` / Postgres extension name | Only change is ORM-generated migration with no manual SQL |
| **`sql-pro`** | Diff includes raw `*.sql` / stored procedure / view DDL AND target is NOT exclusively Postgres, OR user asks for ANSI patterns (CTE, window function, pivot, recursion) | `postgres-pro` is already firing on the same diff |
| **`python-pro`** | Diff touches `*.py` AND EITHER (a) diff >20 Python lines OR (b) touches async / type annotations / Pydantic / FastAPI / Django / pytest fixtures | Change is a config tweak / version bump / trivial dep pin |
| **`prompt-engineer`** | Diff touches prompt template files, system-prompt strings, LLM API call with >5-line prompt, `prompts/` or `templates/` dirs, or agent `*.md` with system-prompt body changes | Change is a typo fix in an otherwise-stable prompt |
| **`refactoring-specialist`** | User invokes `/build` with one of these keywords: `refactor` / `restructure` / `clean up` / `extract` / `rename` / `deduplicate` / `simplify` | `/review`, `/ship`, or `/wrap` is the active command (never fires in review chains). Behavior-preservation is the agent's own responsibility, not a dispatch condition |
| **`react-specialist`** | `package.json` declares `"react"` >=18 AND diff touches `*.tsx`/`*.jsx` AND EITHER (a) user asks for perf optimization, OR (b) diff involves `useMemo`/`useCallback`/`useTransition`/`useDeferredValue`/`Suspense`, OR (c) diff changes state-management strategy (Redux/Zustand/Jotai/Context) | Task is a one-off new component with no existing React context |
| **`docker-expert`** | Diff touches `Dockerfile`, `**/Dockerfile*`, `docker-compose*.yml`, `.dockerignore`, OR request contains `dockerize` / `container image` / `multi-stage` / `image size` / `BuildKit` | Only change is a base-image version bump with no other content changes |
| **`documentation-engineer`** | User invokes docs command, OR diff is >50% docs (`docs/**/*.md`, `README.md` >20 line changes), OR static-site generator config (Docusaurus / MkDocs / Astro docs theme) | Change is a one-line fix in a single doc file |
| **`accessibility-tester`** | Diff touches JSX/TSX/Vue/HTML with `role=` / `aria-*` / `tabindex` / `alt=` / form fields / `<dialog>` / `<modal>` / `<button>`, OR request contains `a11y` / `accessibility` / `WCAG` / `screen reader` / `keyboard nav` / `focus trap` / `contrast` | Diff is pure CSS with no semantic structure change — BUT fires anyway if color contrast is touched |
| **`mcp-developer`** | Diff touches `.claude/mcp*.json`, MCP server code (`@modelcontextprotocol/sdk` in deps, `mcp` package in `pyproject`), MCP tool definition, OR request contains `MCP server` / `MCP tool` / `JSON-RPC 2.0` / `Model Context Protocol` | Change is config-only (adding a known server to `.claude/mcp.json`) with no code touched |

**v0.5 rollout status:** PR 1 pilots `debugger` and `postgres-pro` live. PR 2 adds `sql-pro`, `python-pro`, `prompt-engineer`, `refactoring-specialist` — Tier 1 complete (6 agents). PR 3 adds Tier 2 (`react-specialist`, `docker-expert`, `documentation-engineer`, `accessibility-tester`). PR 4 adds `mcp-developer` opt-in.

---

## Hard-overlap precedence

Ten pairs of agents whose triggers can collide. Each has a precedence rule so only the right one fires (or both fire in documented order).

| Overlap | Who wins on which signal | Both fire? |
|---|---|---|
| `postgres-pro` vs `backend-developer` | `postgres-pro` on Postgres-specific work (JSONB, GIN/BRIN, vacuum, replication, WAL, partitioning). `backend-developer` on service-layer integration (endpoints, where schema fits in service architecture). | Yes, in parallel, when a feature adds both a new endpoint AND a Postgres-specific migration. `backend-developer` designs API contract; `postgres-pro` designs migration/indexes. |
| `sql-pro` vs `backend-developer` | `sql-pro` on raw `.sql` files, stored procedures, view DDL, cross-RDBMS patterns. `backend-developer` on ORM glue (ORM models, query-composition code). | Rarely — `sql-pro` stays in SQL-land, `backend-developer` stays in code-land. |
| `sql-pro` vs `postgres-pro` | `postgres-pro` wins when project declares Postgres (`postgresql` / `pg` in lockfile, `supabase` in deps, `DATABASE_URL` starts with `postgres://`). `sql-pro` wins otherwise. If both would fire by trigger rules → `postgres-pro` takes precedence per Zaude's Supabase-heavy usage pattern. | Discouraged on Postgres projects (just postgres-pro). Allowed on cross-RDBMS projects when raw SQL targets multiple engines. |
| `python-pro` vs `backend-developer` | `backend-developer` does DESIGN (API contract, service architecture, inter-service comms). `python-pro` does IMPLEMENTATION-quality review (types, async correctness, Pydantic usage, pytest structure). | Yes, sequential: `backend-developer` → implement → `python-pro` reviews. Analogous to existing `typescript-pro` pattern. |
| `refactoring-specialist` vs `architect-review` | `architect-review` on NEW construction (new service, new route, new schema). `refactoring-specialist` on EXISTING-code restructure (behavior-preserving). | Never on the same turn — mutually exclusive by construction-vs-restructure gate. |
| `refactoring-specialist` vs `code-reviewer` | `refactoring-specialist` plans the restructure pre-implementation (only on user-invoked refactor signal). `code-reviewer` reviews the resulting diff post-implementation (always). | Yes, sequential: `refactoring-specialist` plans → implement → `code-reviewer` reviews. |
| `react-specialist` vs `frontend-developer` | `frontend-developer` on initial component design (file tree, props, Tailwind recipes). `react-specialist` on React-18+ perf tuning, concurrent features, state-library selection. | Yes, sequential: `frontend-developer` designs shape first, `react-specialist` tunes React-specific parts after. |
| `docker-expert` vs `deployment-engineer` | `docker-expert` on Dockerfiles, multi-stage builds, image size, scanning, SBOMs, registry. `deployment-engineer` on CI pipelines (GitHub Actions, ArgoCD) around the image. | Yes, in parallel, on PRs that modify both Dockerfile AND `.github/workflows/*`. |
| `accessibility-tester` vs `frontend-developer` | `frontend-developer` handles baseline a11y (semantic HTML, `aria-*` attrs, alt text) as normal construction. `accessibility-tester` fires as REVIEWER on a11y-sensitive diffs (modals, forms, focus traps, ARIA attributes, color contrast). | Yes. `frontend-developer` at design, `accessibility-tester` at review time on a11y-sensitive diffs only. |
| `prompt-engineer` vs `architect-review` REVIEW | `architect-review` treats skill/agent `.md` edits as structural changes (new command = new structural element). `prompt-engineer` treats them as prompts (LLM input quality). | Yes, in parallel, on Zaude framework skill-file edits. Different concerns, different outputs — accept the dual-fire on framework work. |

---

## Agent dispatch cap

Hard rule: **max 5 agents dispatched per single `/build` / `/review` / `/ship` turn.**

Zaude's precedent caps are specific to command type:
- `/decision-map` — max 2 agents (1 always-on + 1 conditional)
- `/e2e-test` — max 5 agents (2 always-on + 3 conditional)
- `/microscope` — max 5 agents (`code-reviewer` + `debugger-readonly` always-on pair + up to 3 conditional)
- `/build` / `/review` / `/ship` — max 5 agents per turn

When more than the cap would fire based on trigger rules, apply this **precedence ladder** (highest wins):

1. **Language-specific specialist** — `postgres-pro`, `sql-pro`, `python-pro`, `react-specialist`, `typescript-pro`, `javascript-pro`, `docker-expert`
2. **Framework/domain specialist** — `security-auditor`, `accessibility-tester`, `performance-engineer`, `test-automator`, `debugger`, `mcp-developer`, `prompt-engineer`, `refactoring-specialist`, `documentation-engineer`
3. **Generalist** — `backend-developer`, `frontend-developer`, `architect-review` DESIGN, `workflow-orchestrator`, `design-bridge`
4. **Reviewer** — `code-reviewer`, `architect-review` REVIEW

**Note on `architect-review`:** the agent appears in two tiers by **mode**, not by identity. DESIGN mode sits in tier 3 (generalist — produces a pattern for new construction). REVIEW mode sits in tier 4 (reviewer — checks existing diff structural soundness). The two modes never fire on the same turn (new vs existing construction is mutually exclusive). This is the only documented mode-split exception to the "no agent in two tiers" invariant.

When a specialist fires (tier 1–2), the generalist (tier 3) on the same surface runs in **DESIGN phase only** (not REVIEW) — the specialist covers REVIEW on its dimension.

Concrete application:
- A Postgres-migration diff: `postgres-pro` fires → `backend-developer` runs DESIGN only, not REVIEW.
- A React-perf diff: `react-specialist` fires → `frontend-developer` runs DESIGN only.
- A Python + Dockerfile diff: `python-pro` + `docker-expert` both fire (both tier-1, parallel) → `backend-developer` runs DESIGN only.

**If >5 agents would still fire after precedence:** emit a line in the output — "Dispatch cap reached: <X>, <Y>, <Z> fired; <A>, <B> suppressed per precedence ladder. Re-invoke with `--scope=<agent>` to surface a suppressed dimension."

---

## Parallelization rule

When multiple agents apply to the same task and their work is independent, invoke them in parallel (one message with multiple Agent tool calls). Sequential only when one agent's output feeds the next.

Example parallel chain for a backend + frontend feature:
```
Parallel: [workflow-orchestrator, design-bridge]
     ↓ (wait for both)
Parallel: [backend-developer, frontend-developer]
     ↓ (reconcile API contract)
Implementation
     ↓
Parallel: [code-reviewer, architect-review REVIEW, security-auditor (if applicable)]
```
