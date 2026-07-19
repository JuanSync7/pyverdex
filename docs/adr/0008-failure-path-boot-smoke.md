---
title: Failure-path coverage + boot smoke
kind: adr
layer: backend
status: accepted
owner: Juan.Kok
summary: measure whether each boundary's except-handlers are ever exercised (handler-body lines executed; forcing test named via contexts; handler-less boundaries surfaced as an unprotected worklist) and whether the composition root is ever constructed by a test (factory body lines executed, import-time def lines excluded).
id: adr-0008
created: 2026-07-19
updated: 2026-07-19
visibility: public
canonical: true
---
# 0008 — Failure-path coverage + boot smoke (Phase I)

- **Status:** accepted
- **Date:** 2026-07-19

## Context

Two of the confirmed integration blind spots (roadmap points 5 and 7) were
unmeasured. **Failure paths**: the expensive integration bugs live where the
dependency misbehaves — yet no dimension asked whether a boundary's error
handling ever ran under a test. The vendored ``log_contract_validator``
counts logged branches but records no per-branch line numbers, so it cannot
provide the denominator. **Composition root**: import-smoke proves every
module imports, not that the app can be *assembled* — the factory that binds
settings and wires dependencies can be broken while all its parts import.

The mechanism for both was proven in the Phase H spike: with per-test dynamic
contexts, an except-handler's lines attribute *only to the test that forced
the exception*.

## Decision

1. **Failure-path coverage** (`skills/_failpaths.py`, non-vendored ast):
   - *Denominator* — boundary functions that HAVE error handling. Handler
     semantics: one ``ast.ExceptHandler`` clause **body** is one handler
     (the ``except X:`` clause line can execute on a type-test without the
     handler running, so it is excluded); multiple excepts on one try are
     multiple handlers; nested trys — including inside handler bodies —
     contribute separate handlers (recursive walk); ``except*``
     exception-group handlers (``ast.TryStar``, PEP 654) count the same way;
     ``finally``/``else`` are cleanup/continuation, not recovery, and are
     excluded; a re-raising handler counts as covered when its lines
     executed. The dimension is present whenever anything was mapped
     (handled *or* unprotected boundaries) and absent only when both are
     zero. Same-named defs in one module (method vs function) contribute
     all their handlers under one (module, fn) key — the same documented
     ambiguity as every Phase G/H join.
   - Boundaries with **no** try/except are excluded from the ratio (you
     cannot measure recovery that does not exist) and surfaced as the
     **unprotected boundary** worklist — a first-class "add error handling
     or prove you don't need it" signal.
   - *Numerator* — a boundary's failure path is covered when any handler-body
     line executed (Phase F executed-lines reader); with contexts the report
     names the forcing test(s).
   - v1 scope: handlers *inside* the boundary function; caller-side handlers
     around boundary call sites are deferred.
2. **Boot smoke** (`skills/_detect.py::detect_app_factories` +
   `skills/_boot.py`): composition-root candidates are top-level functions
   with a conventional factory name (create_app/make_app/build_app/get_app/
   build_container/main) OR whose body constructs a framework app object
   (FastAPI/Flask/Starlette/Celery/Typer). A factory is *executed* when any
   **body** line ran under a test — the ``def`` line executes at import time
   and must not count (caught by the Phase I test suite: a merely-imported
   factory read as executed until the join was anchored to the body).
   Module-level ``app = FastAPI()`` wiring executes at import and is already
   the import-smoke sweep's job; only functions are detected. Vendored /
   third-party trees (vendored, node_modules, venvs) are skipped — you don't
   boot code you don't own (dogfood: 10 of 12 detected "factories" were
   vendored tools' CLI ``main()``s before this exclusion).
3. **Report**: two advisory dimensions — ``failure-path`` (warn when handled
   boundaries have unexercised handlers; ``not_run`` when mapped without
   coverage data — mapped is not measured, never fake zeros) and
   ``boot (composition root)`` (warn on unexecuted factories; absent when
   none detected). Fields: ``failure_path_coverage_pct``,
   ``failure_paths_total/covered``, ``boundaries_unprotected``,
   ``app_factories_total/executed`` (executed None without data). Toggles
   ``audit.failure_paths`` / ``audit.boot_smoke`` (default on).

## Consequences

- "The unhappy path was never forced" and "nothing ever assembles the app"
  are now measured, each with a concrete worklist feeding Phase L's typed
  gaps (``failure_path``, ``boot_smoke``), where the generation templates
  can legitimately instruct: *mock the dependency to raise — mocks are the
  correct tool on the failure path* (ADR 0007's realness grading does not
  apply to failure-path forcing).
- Known v1 limits, deliberate: caller-side handlers deferred; factory
  detection is name/constructor heuristic (a DI container assembled in a
  plain helper without framework construction is invisible); handler
  coverage is line-based (a handler that runs but mis-recovers still counts
  as exercised — correctness of recovery is the mutation dimension's job).
