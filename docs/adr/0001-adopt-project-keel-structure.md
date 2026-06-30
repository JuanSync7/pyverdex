---
title: Adopt the Project Keel structure
kind: adr
layer: cross-cutting
status: accepted
owner: Juan.Kok
summary: pyverdex adopts the Project Keel structural standard (subset), phased; LangGraph stays a core engine.
id: adr-0001
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# 0001 — Adopt the Project Keel structure

- **Status:** accepted
- **Date:** 2026-06-26

## Context

pyverdex is a Python LangGraph test-verification engine with a Vite/React
frontend (`web/`), currently shaped as one package (`src/pyverdex/`) plus a
separate web app. [Project Keel](https://github.com/JuanSync7/project-keel) is a
polyglot-aware, agent-friendly project template that standardizes how a
frontend+backend Python project is laid out, labeled, and enforced. We want
pyverdex to reflect that standard so it is legible to humans and agents and
gated against structural drift.

## Decision

Adopt the **structural subset** of Keel, in **phases**, each a reviewable branch
that stays green:

| Phase | Scope |
|-------|-------|
| **1** | The standard + the gate: `CONVENTIONS.md`, root + per-dir `README.md`/`AGENT.md` (`CLAUDE.md` symlinks), `config/project.json`, `scripts/check_structure.py`, `Makefile`, the `docs/` taxonomy, repo hygiene. **No source moves.** |
| 2 | Backend: `src/pyverdex` → `src/backend` with `__init__.py`-as-API (`__all__`) boundaries and `_private` modules; turn on the `check_C`/`check_D` code gates. |
| 3 | Frontend `web/` → `src/frontend/react-vite`; FastAPI `server/` → `api/rest_fastapi` (thin transport); FE↔BE contracts → `src/shared`. |
| 4 | LLM backends → `models/` (adapter + registry); tests → `tests/unit` (mirror) + `integration`/`e2e`/`smoke`; test plans → `test-docs/`. |

Two scoping decisions:

1. **Structural subset only.** Defer `agents/`, `mcp/`, `evals/`, `ops/`, the
   wiki corpus / `llms.txt`, and the AAD agent-surface.
2. **Keep LangGraph as a core engine.** Keel §16 demotes a graph engine to one
   optional adapter behind a neutral stdlib `Plan`/`Runtime`. pyverdex *is* a
   LangGraph engine, so we keep it core (declared as the default runtime in
   `config/project.json`) and **do not** implement the neutral-Plan rewrite.

## Consequences

- A structural gate (`make check`) now fails the build on convention drift; the
  code-boundary checks (`check_C`/`check_D`, plus the `check_E` docstring warning)
  activate automatically once `src/backend/` exists (phase 2).
- `config/project.json` is updated at each phase so it never drifts from the
  tree.
- The big, import-breaking moves are isolated to phases 2–4, each verifiable on
  its own, rather than one large irreversible change.
