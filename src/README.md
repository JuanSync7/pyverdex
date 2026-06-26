---
title: Source
kind: readme
layer: n/a
status: stable
owner: Juan.Kok
summary: All production source. Migrating from src/pyverdex to the Keel src/{frontend,backend,shared,app} layout.
id: src-readme
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# `src/`

All production source. The engine currently lives in the single package
**`src/pyverdex/`** (the LangGraph pipeline, the `skills/` subgraphs, the
deterministic `tools/`, the `report/` builder, the FastAPI `server/`, and the
`models.py`/`config.py`/`backends.py` support modules).

Under the [Keel migration](../docs/adr/0001-adopt-project-keel-structure.md)
this becomes:

- `src/backend/` — the engine (domain/services), `__init__.py`-as-API.
- `src/frontend/` — the UI (today the Vite/React app in `../web/`).
- `src/shared/` — contracts/types used by both.
- `src/app/` — the CLI / composition root.

See [`CONVENTIONS.md`](../CONVENTIONS.md) for the boundary rules.
