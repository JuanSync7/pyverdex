---
title: Test-level taxonomy (smoke / unit / integration / e2e)
kind: adr
layer: cross-cutting
status: accepted
owner: Juan.Kok
summary: pyverdex names the *kind* of test each stage produces as a TestLevel, and a --level selector restricts a run to those stages; levels are orthogonal to coverage tiers.
id: adr-0002
created: 2026-07-01
updated: 2026-07-01
visibility: public
canonical: true
---
# 0002 — Test-level taxonomy (smoke / unit / integration / e2e)

- **Status:** accepted
- **Date:** 2026-07-01

## Context

pyverdex is a measurement-driven loop, not a test pyramid. Its stages are
`lint → fix → audit ⇄ generate → evaluate → integrate → report`. Users
nonetheless reason in *test levels* — "just smoke it", "give me the unit tests",
"do the integration pass" — and [ADR 0001](0001-adopt-project-keel-structure.md)
already anticipates a `tests/{unit,integration,e2e,smoke}` layout in phase 4.

Until now the engine had **no first-class notion of a test level**. The stages
each produce a different *kind* of test (`generate` writes in-process unit tests;
`integrate` writes real-service tests), but nothing named or counted that, and
there was no way to say "run only the unit-level work". Separately, there was no
cheap **smoke** signal: whether the codebase even imports was only observed
indirectly, when the suite happened to import a module.

## Decision

Introduce a `TestLevel` enum — `smoke | unit | integration | e2e` — in
`models.py` (the canonical vocabulary home, alongside the other engine enums),
and make it visible in three places:

1. **Tag records with their level.** `generate` tags every authored/proposed
   test `unit`; `integrate` tags every proposal `integration`. The tag rides on
   the plain-dict record through state and into the report (`FunctionCoverage.
   test_level` for unit tests; a `test-levels` dimension counts every level).

2. **A `smoke` capability in `audit`.** Before any test is authored, the audit
   stage imports every source module in an isolated subprocess
   (`adapters.run_import_smoke`) and records `{total, imported, failures}`. This
   is the deterministic smoke signal — "does it import?" — surfaced as a
   `smoke (imports)` report dimension. It is on by default and toggleable via
   `audit.import_smoke`. Combined with audit's existing suite-run, this makes the
   smoke level real without a new graph node.

3. **A `--level` selector** (CLI `pyverdex run --level …`, server `RunReq.level`)
   that restricts a run to the stages a level needs, via `Config.apply_levels`:

   | Level         | Stages enabled                                  | Produces |
   |---------------|-------------------------------------------------|----------|
   | `smoke`       | audit, report                                   | import-sweep + existing-suite result (no authoring) |
   | `unit`        | audit, generate, report                         | in-process unit tests for line gaps |
   | `integration` | audit, evaluate, integrate, report              | real-service tests for boundary seams |
   | `e2e`         | audit, evaluate, integrate, report *(reserved)* | — (see below) |

   `audit` (measurement) and `report` (output) are always on. `lint`/`fix` are
   pre-flight, not a test level, so a `--level` filter drops them; omit `--level`
   to run the full default pipeline. Multiple levels union their stage sets
   (`--level unit,integration`).

**Levels are orthogonal to coverage tiers.** A *level* selects which stages run;
a *tier* (`Thresholds.tier_for` → critical/standard/cold) sets the coverage bar a
stage must clear. `audit` and `report` never consult the level; the thresholds
never consult it either. Keeping the two axes separate is deliberate — a unit run
and an integration run are both judged against the same tier targets.

**`e2e` is reserved, not faked.** There is no dedicated end-to-end harness yet, so
`--level e2e` currently aliases the integration pipeline. We document that here
(and in the `--level` help text) rather than silently pretending an e2e level
exists. A future ADR will define a real e2e harness and give it a distinct stage
set.

## Consequences

- The report gains two dimensions — `smoke (imports)` (fails if any source module
  fails to import) and `test-levels` (an informational by-level count) — plus
  `tests_by_level` / `smoke_modules_*` fields on `UnifiedCoverageReport` for
  machine consumers. Both appear only when their data is present, so existing
  reports are unchanged.
- `--level` is a run-start concern. `resume` does **not** take it: a resumed run
  replays a checkpoint whose stage config (with the level already resolved into
  stage enables) is frozen, preserving reproducibility.
- The import sweep executes target code at import time, in an isolated subprocess
  with a timeout — the same trust model as running the target's own suite under
  coverage. It excludes `__pycache__`/`.git`/`.venv` and any caller-supplied
  paths, and degrades to an advisory "unavailable" line if it cannot run.
