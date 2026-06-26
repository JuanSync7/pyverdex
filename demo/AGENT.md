---
title: demo — agent rules
kind: rules
layer: n/a
status: stable
owner: Juan.Kok
summary: Local rules for runnable demos.
id: demo-agent
created: 2026-06-26
updated: 2026-06-26
visibility: internal
canonical: true
---
# Agent rules — `demo/`

- Runnable examples that show pyverdex on a real sample project — not tests
  (those live in `../tests/`) and not library code.
- `run_demo.sh` drives a full pipeline over `sample_app/`. Keep it
  self-contained and safe to run repeatedly.
