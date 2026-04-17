# notekit — Project Instructions

A small open-source notes app. This example project demonstrates a realistic Zaude-managed codebase. Copy the shape of this file; adapt the content to your project.

---

## What this project is

**notekit** is a minimal Markdown-based notes app. Single-user, local-first, syncs to a self-hosted backend. Built to demonstrate the Zaude workflow end-to-end; also just a useful notes tool.

## Stack

- **Frontend:** React 19 + Vite 6 + TypeScript + Tailwind v4
- **Backend:** Hono 4 on Bun
- **Database:** SQLite (local-first) with Turso sync
- **Auth:** magic link via Resend
- **Infra:** single VPS, Docker Compose, Caddy for TLS

## Paths

- **Repo:** `github.com/example/notekit`
- **Production URL:** `https://notekit.example.com`
- **Staging URL:** `https://staging.notekit.example.com`
- **Deploy command / CI:** GitHub Actions — push to `main` auto-deploys to staging; merge to `release` deploys to production.

## Hard rules (never violate without explicit override)

- **No external telemetry.** Notes are personal; no analytics, no error tracking that could leak content.
- **SQLite stays local-first.** The backend is a sync server, not the source of truth. Offline must continue to work.
- **Markdown is the interchange format.** Never invent a custom storage format — every note is readable with any text editor.

## What Claude can freely touch

- `src/` (frontend + backend source)
- `tests/`
- `docs/` within the repo
- Dockerfile, docker-compose.yml
- CI config under `.github/`

## What Claude must not touch

- `legacy-sync/` — frozen; the old sync implementation kept for reference until the new one proves itself in production
- `vendor/` — third-party code, untouched

## Domain-specific guidance

- **Testing:** Vitest for frontend, Bun's test runner for backend. CI runs both.
- **Deployment cadence:** weekly releases on Fridays; hotfixes anytime.
- **Known quirks:** the markdown parser uses `remark` + custom footnote plugin; don't swap parsers without a migration plan for existing notes.

## Session start checklist

1. Verify staging is green (`https://staging.notekit.example.com/health`)
2. Check that the Turso replica has synced within the last hour
3. Confirm no PRs are waiting on review older than 48h
