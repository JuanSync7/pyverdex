---
title: Semantic boundary detection + a runner seam
kind: adr
layer: backend
status: accepted
owner: Juan.Kok
summary: evaluate classifies boundaries by the frameworks a module imports (not its filename), and the pytest/coverage path moves behind a Runner protocol as groundwork for other runners.
id: adr-0003
created: 2026-07-01
updated: 2026-07-01
visibility: public
canonical: true
---
# 0003 — Semantic boundary detection + a runner seam

- **Status:** accepted
- **Date:** 2026-07-01

## Context

Two breadth limits made pyverdex narrower than it needs to be — the fifth and
final roadmap phase addresses both as **groundwork** (no behaviour change beyond
the detection improvement; no second runner yet).

1. **Boundary category was guessed from the module name.** `evaluate._category`
   matched substrings in a boundary's *dotted module path* (`db`, `sql`, `queue`,
   `cli`, …) to pick a `BoundaryCategory` and, from it, a lifecycle pattern. A
   module named `handlers.py` that in fact opens a SQLAlchemy session was read as
   `api` and got a `vcrpy` pattern instead of `transaction-rollback`. The name is
   a weak proxy for what a module actually does.

2. **The test runner was hardcoded.** `coverage run -m pytest` and the per-file
   green-run were inlined at their call sites, so pytest was baked in with no seam
   for `unittest` or a non-Python runner.

## Decision

**Semantic, import-based detection.** A new pyverdex helper
`skills/_detect.py:detect_boundary(module, source_root)` resolves the dotted
module to its source file, parses the AST, and classifies by the frameworks it
**imports** — returning a category and a (refined) lifecycle pattern:

| Imports (any of) | Category | Lifecycle pattern (via `_PATTERN`) |
|---|---|---|
| sqlalchemy, psycopg2, psycopg, pymongo, asyncpg, sqlite3, django.db, mysql, motor, aiomysql, aiosqlite, redis | `db` | transaction-rollback |
| celery, kombu, pika, dramatiq, kafka, confluent_kafka, aiokafka, temporalio | `queue` | celery-test-harness (temporalio → workflow-environment) |
| click, typer, argparse | `cli` | subprocess-capture |
| fastapi, flask, starlette, requests, httpx, aiohttp, boto3, openai, urllib3, grpc | `api` | vcrpy |

The canonical, authoritative list is `_FRAMEWORK_SIGNS` in
`src/pyverdex/skills/_detect.py`; this table mirrors it.

`evaluate` calls `detect_boundary(...)` (semantic) first — which returns both a
category **and** a lifecycle pattern — and falls back to
`_category(...)` + the category default when the file can't be read or imports no
known framework. `CATEGORY_PATTERN` in `_detect.py` is the single source of truth
for the category→pattern defaults (evaluate imports it). Scope choices, documented
rather than faked:

- **Per-framework pattern refinement.** The pattern is the category default,
  refined where the *source itself* gives a stronger signal
  (`_PATTERN_OVERRIDES` / `_uses_ddl`): a `db` module that *executes* schema DDL —
  a `create_all`/`drop_all` call or an `alembic` import (bare `MetaData`/`Table`
  construction is definition, not creation, so it does not count) — maps to
  `schema-per-test` rather than `transaction-rollback`; a `temporalio` module maps
  to `workflow-environment`. Overrides are **category-scoped**: only the winning
  category's own refinements apply, so the pattern can never disagree with the
  category (a module importing both `sqlalchemy` and `temporalio` is a `db`
  boundary and stays `transaction-rollback`). Further refinements (testcontainers
  → `ephemeral-container`, Django-migrations DDL) remain future work. The pattern
  is always a valid `LifecyclePattern` enum value.
- **No `file` detection.** `open`/`pathlib` are too ubiquitous to be a reliable
  import signal, so `file` stays with the filename fallback.
- **Precedence** when a module imports several frameworks: `db > queue > cli >
  api`. db/queue are more specific, higher-risk boundary kinds than a generic
  HTTP client, so a repository that imports both `sqlalchemy` and `httpx`
  classifies as `db`.
- **Boundary classification is unchanged** — the vendored `boundary_classifier`
  (gitignored) is not touched; this detector is pyverdex's own code and reads the
  gap record's module path plus `state["source_root"]`.

**A `Runner` protocol seam.** `tools/adapters.py` gains a `Runner`
(`typing.Protocol`) with `collect_coverage(...)` and `green_run(...)`, a
`PytestRunner` default holding the exact historical commands, and
`get_runner(name)` (only `"pytest"` registered). `adapters.collect_coverage` and
`_testrun.green_run` delegate to a runner (pytest by default), and
`Config.runner` (validated at load) selects one — `audit.collect` passes
`get_runner(config.runner)`, so the field is live, not decorative. **pytest is the
only runner; behaviour is identical.** Explicitly out of scope: the vendored
`mutation_runner` (already pluggable via `--test-cmd`) and `flakiness_checker`
(hardcodes pytest internally) — the seam covers pyverdex's own call sites, not the
vendored tools.

## Consequences

- A boundary's category now reflects what its module imports; misnamed modules
  are classified correctly, and the fallback guarantees the old behaviour when no
  framework is detected. Detection is deterministic and stdlib-only (AST).
- The runner seam is real but single-implementation: adding `unittest` means one
  new `Runner` class, a `_RUNNERS` entry, and widening the `Config.runner`
  validator. Until then `config.runner` accepts only `"pytest"` and fails fast on
  anything else.
- New signature/detection surfaces are unit-tested independently of filenames
  (a module named `service.py` importing SQLAlchemy classifies as `db`).
