---
title: Function-to-function edge coverage
kind: adr
layer: backend
status: accepted
owner: Juan.Kok
summary: a stdlib-ast extractor maps internal function->function call edges and a call-site-covered numerator turns that map into a real coverage ratio plus a "what to test next" worklist.
id: adr-0004
created: 2026-07-16
updated: 2026-07-16
visibility: public
canonical: true
---
# 0004 — Function-to-function edge coverage

- **Status:** accepted
- **Date:** 2026-07-16

## Context

pyverdex measured six dimensions, but the "edge (function-to-function)" one was a
**map, not a ratio**: the vendored `coverage_analyzer --edges` emits only
*cross-package, module-to-module* edges (`caller_pkg != callee_pkg`) and reports a
raw count — "N edges mapped". There was no denominator, so it could not answer
"what fraction of the internal call graph is exercised?" nor "which call edge
should I test next?". The vendored analyzer is a gitignored external checkout and
must not be edited, so a finer-grained measure has to live in pyverdex itself.

## Decision

Add a **non-vendored, stdlib-`ast`** extractor and a **call-site-covered**
numerator in `src/pyverdex/skills/_edges.py`:

- **Denominator — `build_function_edges(source_root)`.** Two passes over the
  source tree: first collect every module's *top-level* function names (the
  resolvable callee universe), then walk each module attributing calls to their
  enclosing `Class.method` / `func` qualname. An edge
  `(caller_module, caller_function) -> (callee_module, callee_function)` is
  recorded only when the callee resolves to a top-level function **defined in the
  source tree**, via one of: a bare call to a same-module function, a
  from-imported function (`from util import calc; calc()`), or a call through an
  imported module alias (`import util as u; u.calc()`). `__init__.py` collapses to
  its package name so `from pkg import boot` resolves. External, dynamic, and
  method (`self.x()`, `obj.m()`) calls do **not** resolve to an internal function
  and are excluded — we don't count what we can't measure.
- **Numerator — call-site-covered.** An edge is *exercised* iff any of its
  call-site lines executed, read from the existing coverage.py `.coverage` data
  (`_executed_lines_by_module`). No runtime call tracing is introduced. Known,
  accepted limitation: a covered call site whose branch to the call was never
  taken is a slight over-count. This is the deliberate v1 trade — cheap, reuses
  data we already collect; precise `sys.setprofile` tracing is left as a future
  opt-in refinement.
- **Wiring.** `audit.snapshot` calls `_edges.edge_coverage(project_root,
  source_root)` (toggle `audit.edge_coverage`, default on) and stores
  `state["edge_coverage"]`. `report/builder.py` makes the edge dimension lead with
  the ratio and carries a bounded `uncovered_sample` worklist; the vendored
  cross-package map stays as supporting `detail`. `UnifiedCoverageReport` gains
  `edge_coverage_pct`, `function_edges_total`, `function_edges_exercised`. The web
  verdict row shows `edges <pct> (exercised/total)` when function edges exist.

## Consequences

- The function-to-function dimension is now a **true coverage ratio** with a
  denominator, and every unexercised edge is an explicit "test this next" item.
- Degrades gracefully: with no `.coverage` numerator, `pct`/`exercised` are `null`
  and only the mapped `total` is reported (the dimension still shows the map).
- Resolution is intentionally conservative (static, no method dispatch), so the
  denominator undercounts rather than inventing edges it cannot verify. Method-
  and attribute-dispatch edges are future work, as is precise call tracing.
- Pure stdlib + an optional `coverage` read — no new dependency, consistent with
  the vendored-tool discipline. tree-sitter was considered and deferred: `ast` is
  exact for Python; tree-sitter's payoff is multi-language, which belongs with the
  Runner-seam breadth work (ADR 0003), not here.
