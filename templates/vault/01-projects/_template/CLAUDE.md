# <Project Name> — Project Instructions

Claude reads this file on every session via the SessionStart hook. Keep it short, authoritative, and specific — what Claude needs to know about THIS project that doesn't apply elsewhere.

---

## What this project is

<One paragraph. What it does, who it's for, what stage it's at.>

## Stack

- **Frontend:**
- **Backend:**
- **Database:**
- **Infra:**
- **Auth:**

## Paths

- **Repo:**
- **Production URL:**
- **Staging URL:**
- **Deploy command / CI:**

## Hard rules (never violate without explicit override)

- <Rule 1>
- <Rule 2>

## What Claude can freely touch

- <File/dir patterns Claude can edit without asking>

## What Claude must not touch

- <File/dir patterns that are off-limits>

## Domain-specific guidance

<Anything project-specific: naming conventions, testing strategy, deployment cadence, known quirks.>

## Frozen relationships

<Other projects this depends on / is referenced by. E.g. "reads from project-X's schema", "replaces legacy project-Y".>

## Session start checklist

When Claude enters this project, verify in order:

1. <Check 1 — e.g. "production is live">
2. <Check 2 — e.g. "migrations applied">
