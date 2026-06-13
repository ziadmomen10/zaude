# Zaude 2.0 — changelog

## v2.0.0-preview (2026-06-13)
- NEW: deterministic enforcement kernel (state machine + tamper-evident trace + risk-scaled gates).
- NEW: risk-tier fast lane (`fast`, `fast-ship`) — light by default, gates only high-risk work.
- NEW: GitHub Projects v2 PM layer (Intake→promote→backlog), synced to trace + vault + memory.
- NEW: config-driven generator (policy.json → slash-commands + agents + hook block).
- NEW: portable installer + updater (`install.sh`/`install.ps1`, `zaude update`).
- Carried forward from v1 the same goals; reimplemented as an engine that *enforces*, not advises.
