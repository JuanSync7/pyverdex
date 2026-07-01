---
title: pyverdex — agent rules (root)
kind: rules
layer: cross-cutting
status: stable
owner: Juan.Kok
summary: Root agent rules — the conventions, the gate, and how to work in this repo.
id: agent-root
created: 2026-06-26
updated: 2026-06-26
visibility: internal
canonical: true
---
# Agent rules — pyverdex (root)

These rules are authoritative for the whole repo. Per-directory `AGENT.md`
files inherit from this one; where they conflict, the more specific file wins.

## The standard

- pyverdex follows the **Project Keel** structural standard — read
  [`CONVENTIONS.md`](CONVENTIONS.md) first. It defines the frontmatter scheme,
  the directory taxonomy, the `__init__.py` boundary rule, and the phased
  migration status.
- The structural contract is **checked, not just documented**:
  `scripts/check_structure.py` (via `make check`) fails the build on drift.

## How to work here

- **The gate is the judge.** "Done" means `make verify` (structure + lint +
  types + tests) is green — never a self-report. The structure gate alone is
  `make check`.
- **Slice work vertically and land it in phases.** The Keel migration is
  sequenced in `docs/adr/0001-adopt-project-keel-structure.md`; each phase is a
  reviewable branch that stays green.
- **Keep transports thin.** HTTP/CLI/MCP layers call into the engine; they hold
  no business logic.
- **`__init__.py` is the public API.** Don't reach into another package's
  `_private` modules.
- **Don't commit the vendored trees.** `src/pyverdex/tools/vendored/` and
  `src/pyverdex/knowledge/` are gitignored checkouts of the separate
  juansync-synapse repo; the structure checker excludes them.

## Environment

- Python runs through **`uv` + python3.11** (not the host's system python3).
  Run the suite with `make test` (`uv run pytest`); the web app with
  `make test-fe`.
- The structure checker is pure stdlib and runs under any `python3`.
