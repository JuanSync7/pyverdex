---
title: Per-test attribution via coverage dynamic contexts
kind: adr
layer: backend
status: accepted
owner: Juan.Kok
summary: record which test executed each line (coverage.py dynamic contexts on the existing audit run), join it onto detected boundaries, and grade the system dimension covered / executed_only / uncovered over ALL tests — with an additive rcfile merge because --rcfile replaces the target's coverage config.
id: adr-0006
created: 2026-07-18
updated: 2026-07-18
visibility: public
canonical: true
---
# 0006 — Per-test attribution via coverage dynamic contexts (Phase H1)

- **Status:** accepted
- **Date:** 2026-07-18

## Context

ADR 0005's system dimension had an honest but narrow numerator: only
**engine-written** integration tests counted, so a codebase with an excellent
hand-written suite still read 0% boundary coverage on a measure-only run. The
missing capability was *attribution*: knowing **which test** executed each
line, so every test — hand-written or engine-written — can be credited to the
boundaries it exercises.

coverage.py has this natively: `[run] dynamic_context = test_function` makes
the single coverage run audit already performs record a per-test context for
every executed line, readable via `CoverageData.contexts_by_lineno()`. No
pytest-cov, no runtime tracing, no second run.

## Decision

1. **Collection** (`adapters.collect_coverage(dynamic_contexts=True)`, toggle
   `audit.test_contexts`, default on): there is **no CLI flag** for dynamic
   contexts (only static `--context=LABEL`), and `--rcfile` **replaces**
   config discovery entirely — spike-verified: a target's pyproject `omit` was
   silently dropped under a naive `--rcfile`. So the runner writes a temp
   rcfile that **additively merges the target's own `[run]` options**
   (first-file-wins in coverage's precedence: `.coveragerc`, `setup.cfg`,
   `tox.ini`, `pyproject.toml`; raw parser so `%` in patterns survives) plus
   `dynamic_context = test_function`. Only `[run]` is merged; plugin option
   sections are a documented v1 limitation.
2. **Reader/join** (`skills/_contexts.py`, non-vendored, stdlib + coverage):
   `read_test_contexts` returns `{module: {line: {test labels}}}` (the
   import-time `""` context excluded; `None` when the DB is absent or
   context-free), `function_spans` computes every function/method span with
   its own ast pass (boundary records carry only a start line; same-named
   defs keep separate spans), `boundary_test_attribution` intersects the two.
   Wired into `audit.snapshot` → `state["test_attribution"]`.
3. **Verdicts** (`report/builder.py`): per boundary
   `covered | executed_only | uncovered`. A covering test lifts a boundary to
   *covered* only when the assertion-quality report says it makes a meaningful
   assertion (join on the label's last two segments — test-file stem +
   function — because the label's module prefix is layout-dependent), or when
   the engine's integrate gate passed for that boundary. Execution without
   assertion is **executed_only**: execution is not verification.
   `engine_covered` survives as the loop-closure sub-stat. Without contexts
   the dimension falls back to ADR 0005's engine-only numerator bit-for-bit.

## Pinned facts (spike + regression tests)

- Context label = test module import name + function
  (`tests_pkg.test_api.test_ok` package-style, `test_api.test_ok` bare);
  parametrized variants collapse into one label.
- Except-handler lines attribute only to the test that forced the exception —
  the mechanism Phase I's failure-path coverage builds on.
- A contexts-bearing DB does not change any existing reader's numbers
  (`coverage_totals`, `_edges`, vendored analyzer all union via `analysis2`).
- Overhead ≈10% on the toy fixture; toggle exists, absence degrades.

## Consequences

- The system dimension now measures the *suite's* boundary coverage, graded by
  whether execution was asserted on — dogfooded on pyverdex itself: 60/72
  boundaries executed by 144 attributed tests (Phase G read this as 0/70).
- `boundaries_executed_only` is a new first-class honesty band: "a test ran
  this boundary but nothing meaningful was asserted".
- Known v1 limitations, deliberate: incidental deep-call-chain execution
  counts as execution (no assert-traces-to-boundary analysis); only `[run]`
  config keys are merged; realness tiers (mock/fake/in-process/real) land in
  Phase H2 and will grade *covered* further.
