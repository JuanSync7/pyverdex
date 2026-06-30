---
title: Conventions
kind: doc
layer: n/a
status: stable
owner: Juan.Kok
summary: How pyverdex adopts the Project Keel structural standard, and the phased migration status.
id: conventions
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# Conventions

pyverdex follows the **[Project Keel](https://github.com/JuanSync7/project-keel)**
structural standard — a polyglot-aware, agent-friendly project skeleton. Keel's
`CONVENTIONS.md` is the upstream source of truth; this file records the **subset
pyverdex adopts** and the **migration status**, so the structure checker
(`scripts/check_structure.py`, run via `make check`) has a local contract.

## What pyverdex adopts (the structural subset)

- **`src/{frontend,backend,shared,app}` layout** — UI, server/domain, FE↔BE
  contracts, composition root.
- **Transports are thin** — `api/rest_fastapi/` holds the FastAPI surface and
  only calls into `src/backend/`; no business logic in a transport.
- **Providers behind a registry** — LLM backends live in `models/` (adapter +
  `get_model` registry).
- **Per-directory labeling** — every taxonomy dir carries `README.md` (what +
  frontmatter) and `AGENT.md` (local rules), with `CLAUDE.md` a symlink to
  `AGENT.md`.
- **`__init__.py` is the API** — packages export only through `__init__.py`'s
  `__all__`; implementation modules are `_underscore`d; cross-package contracts
  are Protocols/ABCs in `contracts.py`.
- **`config/project.json`** — the machine-readable project-facts manifest.
- **Mirrored tests** — `tests/unit/` mirrors `src/`; integration / e2e / smoke
  are organized by scenario; `test-docs/` holds plans and the coverage register.
- **A structural gate** — `make check` fails the build on convention drift.

**Deliberately deferred** (not part of this subset): `agents/`, `mcp/`,
`evals/`, `ops/`, the wiki corpus / `llms.txt`, and the AAD agent-surface.

**One deliberate divergence:** Keel §16 demotes a graph engine to one optional
adapter behind a neutral stdlib `Plan`/`Runtime`. pyverdex **keeps LangGraph as
a core engine** (it is the product), declared as the default runtime in
`config/project.json`. We do not implement the neutral-Plan rewrite.

## 1. Frontmatter (labeling for sort/route)

Every Markdown doc (`README.md`, `AGENT.md`/`CLAUDE.md`, `docs/**`) starts with
a YAML frontmatter block:

```yaml
---
title: Backend                       # human title
kind: package                        # see KINDS
layer: backend                       # see LAYERS
status: stable                       # draft|stable|deprecated|template
owner: Juan.Kok
summary: One-line purpose, <=120 chars.
id: src-backend                      # stable, unique across the repo
created: 2026-06-26
updated: 2026-06-26
visibility: public                   # public|internal|confidential|restricted
canonical: true                      # true, or a path/id to the source of truth
---
```

**KINDS:** `readme` `rules` `package` `module` `tests` `test-doc` `doc` `spec`
`design` `adr` `config` `script` `agent` `mcp` `api` `wiki` `demo` `model`
`eval` `container` `ops` `tool`.
**LAYERS:** `frontend` `backend` `shared` `app` `cross-cutting` `n/a`.

Code files can't carry YAML, so the **module docstring** is the label and
`__all__` is the machine-checkable public API.

## 2. Directory taxonomy

| Dir | What goes in |
|-----|--------------|
| `src/frontend` | UI / client (the Vite/React app) |
| `src/backend` | engine: the LangGraph pipeline, skills, deterministic tools, report |
| `src/shared` | contracts/types used by BOTH frontend and backend |
| `src/app` | entrypoints / CLI / composition root |
| `api/rest_fastapi` | the FastAPI dashboard transport (thin over `src/backend`) |
| `models` | LLM backend adapters + registry |
| `tests/{unit,integration,e2e,smoke}` | unit mirrors `src/`; the rest by scenario |
| `test-docs` | test plans, coverage register, strategy |
| `docs/{architecture,specs,design,guides,reference,adr}` | the doc taxonomy |
| `config` | committed defaults + `*.example.*`; the project manifest |
| `demo` | runnable examples |
| `scripts` | dev/CI automation (incl. the structure checker) |

## 3. The `__init__.py` boundary rule

A package's `__init__.py` **is its public API**. Callers import from the
package, never from a submodule. `__init__.py` lists `__all__` and re-exports
only public symbols; implementation modules are `_`-prefixed; cross-package
contracts are ABCs/`Protocol`s in `contracts.py`. *(Enforced by `check_C`/`check_D`,
plus `check_E` which warns on an `__all__`-exported symbol with no docstring — all
three activate once the backend lands in `src/backend/`.)*

## 4. Migration status (phased)

The move from the current single-package layout to the Keel structure lands in
reviewable phases (see `docs/adr/0001-adopt-project-keel-structure.md`):

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Standard + manifest + structure gate + per-dir labeling | **in progress** |
| 2 | Backend: `src/pyverdex` → `src/backend` with `__all__` boundaries | planned |
| 3 | Frontend `web/` → `src/frontend/react-vite`; server → `api/rest_fastapi`; `src/shared` | planned |
| 4 | `models/` (LLM backends); tests → unit-mirror + integration/e2e/smoke; `test-docs/` | planned |

`config/project.json` is updated at each phase so `check_H` always matches the
tree. If you change the scheme (KINDS/LAYERS/STATUSES) update **this file and
`scripts/check_structure.py`** together.
