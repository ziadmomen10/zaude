# notekit — Specification

The spec is what the project IS. Updated when scope changes, not when implementation details do.

---

## Purpose

**notekit** is a local-first, Markdown-based notes app for power users who want text-editor speed with optional cloud sync. It solves the gap between "Markdown in my text editor (no sync)" and "Notion/Obsidian/Evernote (bloated, slow, lock-in)."

## Scope (in)

- Single-user Markdown note-taking with live preview
- Local-first SQLite storage + optional Turso-backed cloud sync
- Magic-link email auth (no passwords)
- Workspace model: one user → many workspaces → many notes
- Attachments (images, PDFs) via object storage, referenced by URL
- Keyboard-driven UX (Cmd+K quick switcher, Cmd+P fuzzy file finder)
- Export to PDF, HTML, plain-text
- CLI (`nk add-note`, `nk sync`) for scripting

## Out of scope

- Multi-user collaboration (no shared workspaces, no real-time co-editing)
- Rich-text WYSIWYG (Markdown only; raw text is the format)
- Mobile apps (web works on mobile browsers; native apps are post-v1)
- Comments, threads, or any social features
- Built-in task management or calendar (use specialized tools)
- E2E encryption (tracked as Q4, deferred)

## Success criteria

- v1.0 ships when:
  - 100 real users have used it for 30+ days
  - Editor frame time stays < 16ms (p99) with 1000-note workspaces
  - Sync p95 latency < 500ms on typical broadband
  - Zero data-loss incidents across all beta users
  - PDF export matches source rendering on macOS, Linux, Windows
  - 90%+ test coverage on sync engine

## Users / personas

1. **Power-user writer** — keyboard-driven, wants speed, values data portability
2. **Developer taking notes** — treats notes like code: version-controlled, plain-text, grep-able

Priority: the writer comes first. Every decision that benefits them > decisions that benefit the developer.

## Non-functional requirements

- **Performance:** Editor typing latency < 16ms p99 up to 1000-line notes. Sync p95 < 500ms on broadband.
- **Availability:** Local-first means offline works. Sync target: 99% uptime.
- **Privacy:** No telemetry. No analytics. Minimal metadata retention (email + auth events only).
- **Compliance:** GDPR-compliant (data-export + deletion endpoints). No PII beyond email.
