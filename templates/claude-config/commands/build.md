Build the feature described in $ARGUMENTS using the full workflow chain. Each step gates the next — if a reviewer finds CRITICAL or HIGH issues, stop and report before continuing.

## Workflow

1. **Plan with workflow-orchestrator** — invoke the `workflow-orchestrator` agent to sequence the work. Its job is to decompose the feature into ordered steps: what data changes, what API/service changes, what UI changes, in what order, with what gates.

2. **Design phase**
   - **If the work touches frontend**: invoke `design-bridge` first to load the current `DESIGN.md` into working context and produce a brief of the design rules that apply to this feature. Then invoke `frontend-developer` with that brief as input to design the components (names, props, file paths, Tailwind class recipes — do not write the code yet).
   - **If the work touches backend**: invoke `backend-developer` to design the API shape, service layer, schema changes, and error semantics (DO not write the code yet).
   - **If the work touches both**: run both in parallel, then reconcile the API contract between them.

3. **Implement the code** inline based on the design output. No design decisions during implementation — if something is underspecified, stop and re-invoke the design agent.

4. **Review phase** — run in order, each must pass before the next:
   - **`code-reviewer`** — reviews the diff for correctness, regressions, style, test coverage
   - **`security-auditor`** — ONLY if the diff touches auth, JWT, passwords, encryption, credential storage, SSH operations, or input validation. Otherwise skip.
   - **`architect-review` in REVIEW mode** — checks structural coherence: service boundaries, error handling, data flow, module cohesion

5. **Report all findings** organized by severity: CRITICAL, HIGH, MEDIUM, LOW. Include file:line references.

6. **Do NOT commit** — wait for the user's explicit approval. If they approve, run `/ship` to commit, push, and update the vault.

## Gates

- If `workflow-orchestrator` flags the feature as out of scope or blocked, stop and report.
- If `design-bridge` finds the feature violates the current `DESIGN.md`, stop and ask whether to update the spec first.
- If `code-reviewer`, `security-auditor`, or `architect-review` returns CRITICAL or HIGH findings, stop and report. Do NOT proceed to commit.
- Trigger rules (non-negotiable): `security-auditor` on any auth/crypto/SSH/credentials/input-validation diff; `code-reviewer` on any code change; `architect-review` on any structural change (new service, new route, new middleware, new schema table, new major component).

## Agent dispatch — single source of truth

For the full 29-agent dispatch matrix (including the v0.5 VoltAgent specialists: `debugger`, `postgres-pro`, `sql-pro`, `python-pro`, `prompt-engineer`, `refactoring-specialist`, `react-specialist`, `docker-expert`, `documentation-engineer`, `accessibility-tester`, `mcp-developer`), read `03-patterns/agent-usage.md` — loaded into context by `SessionStart`. The matrix defines mechanical triggers, hard-overlap precedence rules, and the 5-agent dispatch cap. Never duplicate those rules inline in this file.

## Arguments

$ARGUMENTS — the feature or task description to build. Be specific: which files, which pages, which API endpoints, what behavior.
