---
title: Architecture
kind: doc
layer: cross-cutting
status: stable
owner: Juan.Kok
summary: How the pyverdex engine is structured — the LangGraph pipeline and its dimensions.
id: arch
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# pyverdex architecture

## Goal

Turn the juansync-synapse "test coverage engine" (a set of markdown `SKILL.md`
flowcharts orchestrating deterministic Python tools) into a real, runnable tool
that:

1. shows **proper, multi-dimensional test coverage** (not just line + lint);
2. expresses the flow as a **deterministic LangGraph** instead of prose
   flowcharts;
3. composes the stages into a **configurable loop** with **per-stage human
   gates**.

## Layering

```
pyverdex/
  config.py        Config: thresholds, per-stage enabled+gate, loop, model, paths
  state.py         EngineState (TypedDict) — the LangGraph channel schema
  models.py        Cross-stage pydantic artifacts + UnifiedCoverageReport
  knowledge.py     Loads vendored SKILL.md + rules + protocols → system prompts
  llm.py           ChatAnthropic factory for the judgment nodes
  tools/
    adapters.py    Typed subprocess wrappers → ToolResult (the deterministic layer)
    vendored/      The 10 upstream tools, copied verbatim (self-contained)
  skills/          One compiled subgraph per SKILL.md (lint/fix/audit/generate/
                   evaluate/integrate/report) + _gates.py (interrupt helper)
  graph.py         build_engine(): composes the subgraphs + loop + gates
  report/          builder.py + templates/report.html.j2 (the unified report)
  knowledge/       Vendored SKILL.md/rules/references, TOOL.md, protocol .md
  cli.py           typer CLI: run / resume / version
```

## How each design decision maps back

| juansync-synapse | pyverdex |
|---|---|
| `SKILL.md` flowchart (prose) | a compiled `StateGraph` subgraph in `skills/` with named internal nodes |
| skill rules + TDD `protocols/*.md` | system-prompt material loaded by `knowledge.build_system_prompt()` |
| deterministic `src/tools/testing/<tool>` | vendored verbatim under `tools/vendored/`, wrapped by `tools/adapters.py` |
| on-disk hand-off artifacts (`LINT_REPORT.json`, `AUDIT_GAP_REPORT.json`, `COVERAGE_STATE.yaml`) | typed channels in `EngineState`, persisted by the SQLite checkpointer |
| "each stage only *suggests* the next; handoff is the user's call" | deterministic conditional edges + `interrupt()` gates you toggle per stage |
| scattered constants (line 95/85/70, kill 1.0, assertion 0.5, flake 2%) | one `Config` / `config/default.yaml` |
| Ralph budget N=10 | `loop.max_cycles` |

## State & the loop

`EngineState` is a `TypedDict(total=False)`; every node returns a partial update
that LangGraph merges. `log`/`errors` use a custom `_accumulate` reducer that is
**safe across nested subgraphs** — a plain `operator.add` double-counts because a
compiled subgraph shares the channel and returns the cumulative list, which the
parent would add again.

The `audit → generate → audit` self-loop is a conditional edge out of `audit`:

```python
def after_audit(state):
    if generate_enabled and not state["coverage_met"] \
       and state["cycle"] < max_cycles and not state["loop_exhausted"]:
        return "generate"
    return <evaluate | integrate | report>   # first enabled
```

`audit` sets `coverage_met` (no function below its tier target); `generate`
increments `cycle` and sets `loop_exhausted` when it has no further work this
run. (`loop_exhausted` **must** be a declared channel or LangGraph drops it and
the loop never stops — a bug we hit and fixed.)

## Human gates (per-stage toggle)

`skills/_gates.py::human_gate` calls `interrupt()` only when
`config.is_gated(stage)`. The CLI drives the engine with a SQLite checkpointer;
on interrupt it surfaces the pending gate and either auto-approves (`--yes`) or
pauses for `pyverdex resume`. Resume passes `Command(resume={"approve": ...})`.

## The unified report — the headline output

`report/builder.py` merges, per function `(module, function_name)`:
line % + missing lines (coverage.py), branch count (branch_mapper), mutation
kill-rate (mutation_runner, when generate ran it), plus cross-package edges and
per-test assertion quality. It computes a per-dimension rollup and an overall
verdict (`fail` if any dimension fails, `warn` if any `not_run`, else `pass`),
and writes `coverage-report.{json,html}`.

## What is real vs. stubbed today

- **Real, tested**: config, knowledge/prompt assembly, all 10 deterministic
  adapters, the audit measurement core, the unified report, the graph wiring,
  the audit⇄generate loop, and HITL interrupt/resume.
- **Propose-only**: `fix` runs `ruff --fix` (deterministic) and produces an LLM
  remediation *plan*; `generate`/`integrate` author *candidate* tests for the
  gate but do not write files unattended. The hooks for applying changes +
  per-gap mutation gating are in place — flip them on per project.
- **Omitted, not faked**: dimensions whose upstream tool never existed
  (`critical_scorer`, `gaming_detector`, `dep_vulnerability`,
  `edge_coverage_analyzer` as a separate tool — edges come from
  `coverage_analyzer --edges`).

## Next steps

1. Apply-mode for `generate` (write the approved test, re-run `audit`, run
   `mutation_runner` per gap as a hard gate) so the loop actually closes gaps.
2. Branch *execution* coverage (run coverage.py in branch mode and intersect
   with `branch_mapper`) for true branch %, not just structural counts.
3. `integrate` apply-mode with `flakiness_checker` + cassette `secret_scanner`
   gates, as the upstream test-integrate skill specifies.
