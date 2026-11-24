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

- **Status:** proposed (rulings R1–R10 are the owner's; P1–P4 are proposals awaiting a ruling)
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

## Proposals (not yet ruled)

- **P1 Packaging.** The Python playbooks are exported into this repo as a
  rendered pack with a digest, the same way the owner's rule decks are packaged
  as a plugin. The private store stays the source; this repo never edits a
  rendered file, and a drift test fails on a digest mismatch. A redaction pass
  runs before export, because this repo is public.
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

## Open questions

1. Own the measurement tools here (roadmap Q4): they are copied in from a
   retired repo and not committed, so a fresh clone cannot run.
2. Trace results to intent (roadmap Q6): today every test pyverdex writes is
   derived from the code it tests, so coverage and mutation show the tests
   pin the current behaviour, bugs included, not that the code does what was
   asked.
