---
title: Config
kind: config
layer: n/a
status: stable
owner: Juan.Kok
summary: Committed configuration — engine defaults and the project-facts manifest.
id: config-readme
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# `config/`

Committed configuration — data the app reads, never logic, and never secrets
(those live in the environment / `.env`).

- `default.yaml` — the engine configuration (thresholds, the audit⇄generate
  loop bounds, per-stage gates, the LLM provider). All values are the built-in
  defaults; override only what you need.
- `project.json` — the machine-readable **project-facts manifest** (CONVENTIONS
  §15), enforced by `scripts/check_structure.py` (`check_H`) so it can't drift
  from the tree.
