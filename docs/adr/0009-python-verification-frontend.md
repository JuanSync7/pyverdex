---
title: pyverdex as the Python verification frontend over packaged playbooks
kind: adr
layer: cross-cutting
status: proposed
owner: Juan.Kok
summary: pyverdex becomes playbooks (procedure + rules) plus a deterministic code layer (measurement, checks, a goal-driven loop runner); self-contained and runner-agnostic.
id: adr-0009
created: 2026-11-24
updated: 2026-11-24
visibility: public
canonical: true
---
# 0009 — pyverdex as the Python verification frontend over packaged playbooks

- **Status:** proposed (rulings R1–R16 are the owner's; P2–P5 are proposals awaiting a ruling)
- **Date:** 2026-11-24

## Context

The judgment stages (fix / generate / evaluate / integrate) build their prompts
from a vendored copy of the older juansync-synapse test skills. The owner's
newer test playbooks (unit, integration, mutation, coverage, test plan) have
superseded those skills, so pyverdex's prompts have fallen behind and the
engine has seen little use. The measurement half (line, branch, edges,
boundaries, realness, failure paths, mutation, assertion quality) remains the
part no playbook provides.

**Goal (owner):** a robust, end-to-end run that lets someone who does not read
Python be confident in code an agent implemented.

## Rulings (owner, 2026-11-24)

- **R1** pyverdex is the frontend for Python verification: playbooks (procedure
  and rules) plus a deterministic code layer on top.
- **R2** Runner-agnostic: it runs on its own (starting its own agent) and as a
  tool under an external orchestrator.
- **R3** Self-contained: running pyverdex never needs access to the owner's
  private playbook store. Anyone who clones it can run it.
- **R4** What is good in the old synapse test skills and missing from the newer
  playbooks is ported into the playbooks.
- **R5** Goal-driven loop: the user supplies targets (for example "lint clean,
  90% coverage, with real assertions") and the agent loops until the targets
  are met.
- **R6** "With assertions" means both an assertion-quality target and a
  mutation kill-rate target. Coverage alone counts for nothing.
- **R7** The standalone runner (pyverdex starts its own agent) ships first; the
  tool-under-orchestrator mode follows once measuring and judging are separate
  commands.
- **R8** Targets live in a typed `targets:` section of `config/default.yaml`,
  with `--target key=value` overrides; every run records the targets it used.
- **R9** For tests written against code that already exists, killing a planted
  mutant replaces "the new test fails at the base commit". Tests for new code
  still must fail at base.
- **R10** No quarantine for flaky tests (a flaky test is a defect to fix), and
  no nightly-only tests: a nightly run may be an extra, never instead of the
  one gate.
- **R11** pyverdex owns its measuring tools: they are committed and tested
  here, and the sync script from the retired repo goes.
- **R12** Playbooks move between their private source and this repo by pull
  request in both directions, the way a local and a remote clone do. There is
  no one-way sync.
- **R13** A test is never derived from the code it tests: that is marking your
  own homework. Every test traces to an approved expectation (the ask, scope,
  requirement, design or test plan). There is no "derived from code" category,
  and the mode that writes tests from coverage gaps is removed. An uncovered
  line is a question for the spec (is this behaviour wanted?) or dead code,
  never a prompt to write a test.
- **R14** The author of the code never writes the tests that judge it, and this
  is enforced outside the model, not left to an instruction.
- **R15** The run ends in outputs a non-Python reader can trust: a
  plain-language verdict page, the real entry points run from a clean clone,
  changed code judged on its own, and "lint clean" meaning style, types,
  security and dependency checks.
- **R16** Code-quality checks live in both pyverdex and the playbooks:
  idempotency, exit codes, error handling (nothing swallowed), message
  wording, and dead code, unreachable code and dangling branches.

## Proposals (not yet ruled)

- **P1 Packaging.** Superseded by R12. What carries over: a pull into this
  repo is redacted first (this repo is public), and a change made here to a
  generated rules file goes back as a change to its source, never as an edit
  of the generated file.
- **P2 Measurement as kernel, judging as checks.** Measurement is a kernel tool
  that writes an evidence file (the pyverdex report JSON). Each target is held
  by a stdlib check (`playbook-check/1`) that reads only that file. The builder
  (agent + tools) and the judge (checks) stay separate.
- **P3 Loop stop rules.** The loop ends only on (a) every target check passing,
  (b) a cycle or spend cap, or (c) a stall (no measured progress for N cycles).
  It never ends on the agent's own report. The agent may not edit checks, kernel,
  config, thresholds or coverage exclusions, or delete tests; a check holds each.
- **P4 Freeze.** No new LLM-loop features (Phase L) until roadmap slices S1–S4
  land. Measurement work (Phase I, PR #15) is unaffected.
- **P5 The split.** One test decides where a piece lives: if it needs a
  package, a subprocess or a sandbox, it is pyverdex; if it is files and the
  standard library, it is the playbook. The playbooks hold the procedure, the
  rules, the review questions, every judging check, and the evidence format
  (the judge owns the contract). pyverdex holds the measuring engine, the
  sandbox, the loop and its author separation, and the verdict outputs; its
  transports (CLI, MCP, web dashboard) stay thin. A playbook used alone calls
  `pyverdex measure` as its kernel tool where it needs a measurement, then
  runs its own checks.

## Open questions

1. The split (P5): measuring tools in pyverdex, or in the playbook kernels?
2. Existing code with no written expectations: where do its expectations come
   from, given R13?
