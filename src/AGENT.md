---
title: src — agent rules
kind: rules
layer: n/a
status: stable
owner: Juan.Kok
summary: Local rules for production source under src/.
id: src-agent
created: 2026-06-26
updated: 2026-06-26
visibility: internal
canonical: true
---
# Agent rules — `src/`

- Production code only. Tests live in `../tests/`; transports in `../api/`;
  dev scripts in `../scripts/`.
- A package's `__init__.py` is its public API (`__all__`); implementation
  modules are `_`-prefixed; never import another package's `_private` module.
  *(Enforced by the structure checker once the backend moves to `src/backend/`.)*
- `src/pyverdex/tools/vendored/` and `src/pyverdex/knowledge/` are **gitignored
  vendored checkouts** of the separate juansync-synapse repo — do not edit or
  commit them; repopulate via `scripts/sync-vendor.sh`.
