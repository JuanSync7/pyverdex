---
title: Scripts
kind: script
layer: n/a
status: stable
owner: Juan.Kok
summary: Dev and CI automation, including the structure checker.
id: scripts-readme
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# `scripts/`

Dev/CI automation and one-shots — not importable library code.

- `check_structure.py` — the structural gate (`make check`): frontmatter,
  taxonomy labeling, the `config/project.json` manifest, and the
  `CLAUDE.md`→`AGENT.md` symlinks. Pure stdlib; runs under any `python3`.
- `sync-vendor.sh` — repopulate the gitignored vendored juansync-synapse trees
  under `src/pyverdex/`.
