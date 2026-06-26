---
title: scripts — agent rules
kind: rules
layer: n/a
status: stable
owner: Juan.Kok
summary: Local rules for dev/CI automation.
id: scripts-agent
created: 2026-06-26
updated: 2026-06-26
visibility: internal
canonical: true
---
# Agent rules — `scripts/`

- Scripts are doers: stdlib-leaning, idempotent, with `--help` where it helps.
  No importable library code lives here (that's `src/`).
- `check_structure.py` is the structural gate. If you change the convention
  scheme, update `CONVENTIONS.md` **and** this checker together, then re-run
  `make check`.
- Keep the checker pure-stdlib and 3.6-safe so it can run in pre-commit/CI under
  the host's old `python3`.
