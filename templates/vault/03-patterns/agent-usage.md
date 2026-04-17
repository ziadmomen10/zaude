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
