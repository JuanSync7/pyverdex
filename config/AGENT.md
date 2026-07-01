---
title: config — agent rules
kind: rules
layer: n/a
status: stable
owner: Juan.Kok
summary: Local rules for configuration.
id: config-agent
created: 2026-06-26
updated: 2026-06-26
visibility: internal
canonical: true
---
# Agent rules — `config/`

- Configuration is **data**, not logic, and **never a secret** — API keys/tokens
  go in the environment (`.env`, gitignored), never here.
- `project.json` is a committed decision read by the checker, not the app. When
  a phase moves the backend/frontend/transport, update it so `check_H` keeps
  matching the tree.
- Runtime tunables stay in `default.yaml` (YAML, app-facing); machine facts stay
  in `project.json` (JSON, checker-facing). Don't merge the two.
