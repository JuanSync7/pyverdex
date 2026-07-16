---
title: System (boundary) coverage + surfacing log-path
kind: adr
layer: backend
status: accepted
owner: Juan.Kok
summary: turn the boundary map into a system-coverage ratio (boundaries with a passing integration test) with an untested-boundary worklist, and surface the log-path coverage that audit already collected but the report dropped.
id: adr-0005
created: 2026-07-16
updated: 2026-07-16
visibility: public
canonical: true
---
# 0005 — System (boundary) coverage + surfacing log-path

- **Status:** accepted
- **Date:** 2026-07-16

## Context

Phase F gave the function→function dimension a denominator. Two related gaps
remained at the *system* level:

1. **No system/e2e coverage ratio.** `boundary_classifier` detects external
   boundaries (`http_handler`, `env_reader`, `stdin_reader`, `exported_public`,
   …) and audit stores them in `state["boundary_report"]`, and the integrate
   apply path writes real-service tests recorded in `state["generated"]`
   (`boundary_fn` + `test_path` + `gate`). But nothing joined the two: there was
   no "what fraction of external boundaries actually has a passing integration
   test, and which don't?".
2. **A measured dimension was silently dropped.** `audit.snapshot` runs
   `log_contract_validator` and stores `state["log_contract_report"]`
   (`log_path_coverage`, `branches_with_log/total_branches`, `violations`), but
   `report/builder.py` never read it — the metric was computed and thrown away.

## Decision

Both are pure `report/builder.py` joins over state we already collect — no new
tools, no vendored edits.

- **System (boundary) coverage.** Denominator = the boundaries in
  `boundary_report`. Numerator = boundaries with a **passing** engine integration
  test, i.e. a `generated` record carrying `boundary_fn` + `test_path` +
  `gate == "pass"`, matched to a boundary on `(module, function_name)`. Emits
  `boundary_coverage_pct`, `boundaries_total`, `boundaries_covered`, and a
  `system (boundary coverage)` dimension whose `untested_sample` is the
  "what to test next" worklist. The dimension is **advisory-warn, not fail**,
  when boundaries are untested: a measure-only run has written no integration
  tests yet and that must not red the gate (a `warn` dimension does not fail the
  overall verdict). `boundary_coverage_pct` is `None` and the dimension is
  omitted when no boundaries were detected.
- **Log-path.** Surface `log_contract_report` as a `log-path` dimension
  (`log_path_coverage_pct`, branches-with-log ratio). Violations are advisory:
  they set the dimension to `warn` (never fail), since log contracts are
  heuristic and often run without a `LOG_POLICY.yaml`.
- **Web.** New `systemLabel()` in `api.ts` (pure, tested) renders
  `system <pct> (covered/total)` in the verdict row when boundaries exist;
  report type + sample report updated.

## Consequences

- System/e2e is now a **coverage ratio with a denominator** and an explicit
  untested-boundary worklist — the same shape as Phase F edges, parallel to the
  "measure, then know what to test next" goal.
- The numerator reflects **engine-written** integration tests (the loop closing),
  not pre-existing suite coverage of a boundary — that remains the line dimension.
  This keeps the dimensions orthogonal and the meaning honest; documented so the
  0% measure-only baseline reads as "no integration tests written yet", not "the
  boundary is unreachable".
- Log-path coverage is no longer computed-and-discarded; it appears as an
  advisory dimension without changing pass/fail semantics.
