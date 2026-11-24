---
title: Roadmap — pyverdex as the Python verification frontend
kind: doc
layer: cross-cutting
status: draft
owner: Juan.Kok
summary: The ordered slices, open owner questions and found gaps for turning pyverdex into playbooks plus a deterministic measure-judge-loop layer (ADR 0009).
id: roadmap
created: 2026-11-24
updated: 2026-11-24
visibility: public
canonical: true
---
# Roadmap: pyverdex as the Python verification frontend

The decision record is [ADR 0009](adr/0009-python-verification-frontend.md).
This file holds the plan. **Planned** and **done** are kept apart; a slice is
done only when `make verify` is green on its branch.

**Goal:** a robust, end-to-end run that lets someone who does not read Python
be confident in code an agent implemented.

## Owner questions

| # | Question | Answer | Blocks |
|---|---|---|---|
| Q1 | Which runner ships first? | **Ruled (R7):** standalone. | S4 |
| Q2 | Where do targets live? | **Ruled (R8):** typed `targets:` in `config/default.yaml` plus `--target`. | S1 |
| Q3 | What proves a test for existing code can fail? | **Ruled (R9):** a killed planted mutant. New code still fails at base. | S4 |
| Q4 | Own the measuring tools? | **Ruled (R11):** yes; retire the sync script. | S0 |
| Q5 | Quarantine and nightly-only tests? | **Ruled (R10):** drop both. | — |
| Q6 | Label results "derived from code"? | **Ruled (R13):** no such category; tests never come from code. | S1 |
| Q7 | The split. | **Ruled (R17):** same product, different offerings: the deterministic tools ship in the playbook pack and run without pyverdex; pyverdex adds the loop, agents, sandbox launcher and verdict page. Detail in ADR P5. | S0, S5 |
| Q8 | Existing code with no written expectations. | **Ruled (R18):** a deterministic tool extracts the public interface; a fresh author sees only it and the owner's answers. Interface bugs handled per ADR P6. | S4 |

## Slices (persistent formats first)

**S0 — Own the tools and a baseline.** Commit the ten measuring tools as
pyverdex code; retire `scripts/sync-vendor.sh`; change `.gitignore`, the
structure checker's exclusions and the agent rule files together. The old
prompts stay a stop-gap until S5. Run `make verify` on the batch farm inside
the isolation wrapper (the suite runs the real mutation tool). Land or park
PR #15 first: it changes the files S1 to S4 change. The tools are about
5,100 lines; their only needless dependency is pydantic (schemas), which
goes to standard-library dataclasses so they can ship in the pack (R17).

**S1 — Formats.** The evidence file (versioned JSON, inputs digest): every
dimension says measured, not measured or not applicable; every test names the
plan row it proves; every file records which run wrote it. Typed `targets:`.
pyverdex reads the test-plan format the playbooks already write.

**S2 — Judges.** Standard-library checks reading only the evidence and the
diff: static (style, types, security, dependencies, dead and unreachable code,
swallowed errors), coverage, assertion quality, mutation kill rate,
traceability (every plan row has a test; no test without a row), author
separation (no run wrote both code and its tests), and anti-gaming (added
suppressions, `pragma: no cover`, coverage omits, target edits, deleted or
skipped tests). The CLI exits non-zero on any failure.

**S3 — Sandbox.** The mutation tool itself works on a copy and refuses to
edit in place, so it is safe wherever it ships. Under pyverdex it also runs in a private process namespace or a
no-network container, and the original is checked unchanged by hash. The same
sandbox gives each agent only its own inputs: the test author gets the plan
and the interface, never the implementation.

**S4 — The loop.** Plan (approved) → tests by one author → code by another
(a different model family where possible) → measure → judge, ending only on
the verdicts, a cycle or spend cap, or a stall, with the reason written down.
The mode that writes tests from coverage gaps is removed. For existing code:
extract the interface (no model), ask the owner plain-language questions,
turn surviving mutants into neutral questions (ADR P6).

**S5 — Playbooks by pull request.** Ship the deterministic tools out to the
pack (each file has one home, R17), and pull the Python playbooks into this repo
(redacted) and push changes back to their source, both as pull requests. Fill
the playbook gaps: the unit, integration and mutation playbooks have checks
but no procedure; there is no static-analysis measure, coverage target, stall
rule, or check on the code-quality items in R16.

**S6 — Confidence outputs.** The plain-language verdict page (each
expectation, pass or fail, what was not measured); the real entry points run
from a clean clone and the lockfile, twice, to show they are idempotent;
changed code judged on its own.

**Queued, not planned yet:** the smallest test set (a report of tests that kill
no mutant and prove no plan row the others do not; never an automatic
deletion); tests held back from the code's author; CI running `make verify`;
Keel structure phases 2 to 4. **Frozen:** new judgment-loop features until S1
to S4 land (ADR P4).

## Done

- ADR 0009 drafted (status: proposed); rulings R1 to R18 recorded.
- Read-only audits of both sides: the older test skills against the current
  playbooks, and this code against the playbook check contract.
