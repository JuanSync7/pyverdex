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
   - *Numerator* — a boundary's failure path is covered when a named test
     executed a handler-body line (per-test contexts); the report names the
     forcing test(s). A handler that only ran at import time is not covered.
     Which lines count is read from the compiler's own line tables
     (`skills/_lines.py`; the source is compiled, never executed), not
     predicted from the syntax tree: a line counts for a handler only when
     the boundary function's code is the *only* code that can emit it and it
     lies in the handler body past the header. That leaves out a header line
     (the type test runs it without entering the body) and any line shared
     with code that runs later (a nested function, class, lambda,
     comprehension, or a lambda used as a default). Each handler gets one of
     three verdicts: *ran* (a named test ran such a line), *did not run*
     (none ran, and the first line the body emits is itself such a line, so
     entering the body would have been seen), or *unknown* (everything
     else, e.g. ``except X: return 0``). A boundary is covered when any
     handler ran, a measured zero only when every handler did not run, and
     otherwise *not measurable*: left out of the ratio and listed by name.
     The price: a handler or factory whose first line is shared (it opens
     with a nested ``def``, or with a statement holding a lambda) can be
     reported as run but never as a measured zero. The rule is checked
     against a real tracer over generated bodies
     (`tests/test_phase_i_line_anchors.py`). Line tables belong to the
     interpreter that compiles them, so the audit must run on the same
     Python version as the measured run (it does: one environment runs both).
     A module the target leaves out of measurement (``omit``) is unknown,
     not zero; a module no test imports is still measured, as a zero. A static
     coverage label set by the target (``context = ...``) is dropped for the
     run, because it would stamp import-time lines as if a test ran them.
     Without per-test contexts nothing is measured: the dimension is
     not-run, never a ratio.
   - Handlers of functions, lambdas and classes defined *inside* the boundary
     belong to those, not to the boundary.
   - A measured run in which no boundary has a handler still reports: the
     dimension warns and carries the unprotected worklist.
   - v1 scope: handlers *inside* the boundary function; caller-side handlers
     around boundary call sites are deferred.
2. **Boot smoke** (`skills/_detect.py::detect_app_factories` +
   `skills/_boot.py`): composition-root candidates are top-level functions
   with a conventional factory name (create_app/make_app/build_app/get_app/
   build_container/main) OR whose body constructs a framework app object
   (FastAPI/Flask/Starlette/Celery/Typer). A factory is *executed* when a
   named test ran a **body** line (per-test contexts) — the ``def`` line
   executes at import time and must not count, and neither does a
   module-level call such as ``app = create_app()``. The same line rule and
   the same three verdicts as for handlers apply: a route or helper defined
   inside the factory and called later by a test does not show the factory
   ran. A factory that cannot be judged is *not measurable*: listed by name,
   never executed and never a measured zero; when no factory is measurable the
   dimension is not-run. Without per-test contexts the dimension is
   not-run.
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
