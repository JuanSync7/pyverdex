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

## Owner questions (each blocks the slices it names)

Each carries a predicted answer to confirm or correct.

| # | Question | Answer | Blocks |
|---|---|---|---|
| Q1 | Which runner ships first? | **Ruled (ADR R7):** standalone. | S4 |
| Q2 | Where do targets live? | **Ruled (ADR R8):** typed `targets:` in `config/default.yaml` plus `--target` overrides. | S1 |
| Q3 | What proves a test for existing code can fail, when it passes at base? | **Ruled (ADR R9):** killing a planted mutant. New code still fails at base. | S4, S5 |
| Q4 | The ten measuring tools (mutation runner, assertion scorer, coverage, branch and boundary mappers, lint, secrets, flakiness, log contract, Hypothesis strategies) and the old prompts are copied in by `scripts/sync-vendor.sh` from a repo that is no longer used, and are not committed. A colleague who clones pyverdex gets an engine with no tools. Own them here? | Predicted: commit the ten tools as pyverdex's own code, tested here, and retire the sync script. The old prompts stay a stop-gap until S5 replaces them. This reverses the "don't commit the vendored trees" rule, so `.gitignore`, the structure checker's exclusions and the agent rule files change together. | Step zero, ADR R3, CI |
| Q5 | Quarantine and nightly-only tests? | **Ruled (ADR R10):** drop both; nightly only as an extra. | Nothing now |
| Q6 | Does the evidence file trace each result to an approved plain-language expectation (a test-plan row), labelled "traced to intent" or "derived from code"? | Predicted: yes. pyverdex reads the plan format the test-plan playbook already writes; code-derived tests stay allowed but are labelled and never count towards the intent target. | S1 |

## Step zero: a baseline

- `make verify` has never run in this checkout (the vendored tree is not
  synced). Sync it and run the suite on the batch farm; record the result.
- PR #15 (failure-path coverage + boot smoke) changes `audit.py`,
  `report/builder.py`, `state.py`, `config.py` and `models.py`, which are
  the files S1 to S4 change. Review and land it, or park it, before S1.

## Slices (persistent formats first)

**S1 — Evidence and targets formats.** `pyverdex measure` writes a versioned
evidence file (JSON, with an inputs digest). Every dimension says
`measured`, `not measured` or `not applicable`; "not measured" is never a
zero or a pass. A typed `targets:` config holds lint errors, line and branch
coverage, assertion quality, mutation kill rate, the cycle cap, the stall
window and the spend cap.
*Done when:* the schema and its loader are tested, including an unset, a
valid and an invalid value for each key.

**S2 — Judges.** One small check per target, standard library only, reading
only the evidence file and the diff, with a fail-closed exit table (pass,
findings, usage, config, input, empty, bug). The checks are: lint, coverage,
assertion quality, mutation kill rate, and an anti-gaming check that fails on
added `pragma: no cover`, suppression comments, coverage omit or exclude
entries, threshold or target edits, and deleted or skipped tests. The CLI
exits non-zero when any check fails.
*Fixes found by the audit:* the loop counts coverage as met when there is no
line data; edge coverage reads 100% when nothing was measured; `pyverdex run`
never exits non-zero.
*Done when:* each check is shown failing on a planted bad input.

**S3 — Sandboxed mutation.** The mutation tool edits the real source file in
place and restores it from an in-memory backup. A SIGKILL cannot be caught,
so a killed run leaves the file mutated. Mutate a copy of the tree, inside a
private PID namespace or a no-network container, and confirm the original is
unchanged by hash afterwards.
*Done when:* a mutation run outside the sandbox refuses to start, and a
killed run leaves the original tree byte-identical.

**S4 — Loop controller.** The loop ends only on S2 verdicts, the cycle cap,
the spend cap, or a stall (no measured progress for N cycles, or the same
failure repeated). It writes a termination reason. Generated tests that
failed their gate are removed before the next measurement, so they cannot
raise coverage.
*Done when:* a run on the demo app ends on each of the four reasons in a test.

**S5 — Prompts from packaged playbooks.** The judgment stages build their
prompts from an exported playbook pack (rendered, digest-pinned, redacted
before export) instead of the older vendored skills. A missing prompt file
fails the run instead of becoming an empty prompt.
*Done when:* a drift test fails on a digest mismatch.

**Gaps for the goal** (proposed, new scope; ruled one at a time):
- *In the playbooks, not wired into pyverdex:* a plan of plain-language
  expected results that a stranger could test from; the code's author never
  writes the tests that judge it (today `generate` reads the implementation);
  every plan row traced to a test; an end-to-end test for every entry point;
  a reviewer from a different model family.
- *In neither:* a one-page verdict a non-Python reader can check (each
  expectation, pass or fail, what was not measured); running the real entry
  point from a clean clone and the lockfile; judging changed code on its own
  so a whole-codebase average cannot hide an untested change; "lint clean"
  defined as style, types, security and dependency checks, not style alone.

**Queued, not planned yet:** playbook-source changes from R9 (the fail-at-base
check accepts a killed mutant for pre-existing code) and R10 (quarantine and
nightly-only are not ported); a CI job that runs `make verify` (needs Q4);
Keel structure phases 2 to 4; further measurement phases. **Frozen:** new
judgment-loop features until S1 to S4 land (ADR 0009 P4).

## Gaps found

**Playbook side** (fixed in the playbook source, then re-exported; listed
here by label only):
- no lint, type or dead-code measure, and no severity table;
- no check on added suppression comments or `pragma: no cover`;
- no numeric coverage measure or coverage target;
- gaming checks run on changed tests only; nothing scans the whole suite
  (mocking the code under test, copy-pasted tests, self-referential helpers);
- no flakiness measure;
- no procedure for lint fixing, for writing tests against existing code from
  a coverage gap, or for converting mock tests to real ones;
- the loop rule names a cap but no stall or same-failure stop.

**pyverdex side** (beyond S1 to S4):
- the Hypothesis dimension has no test;
- flakiness is only monkeypatched in the tests;
- lint is not part of the loop's stop condition.

## Done

- ADR 0009 drafted (status: proposed); rulings R7 to R10 recorded.
- Read-only audits of both sides: the older test skills against the current
  playbooks, and this code against the playbook check contract.
