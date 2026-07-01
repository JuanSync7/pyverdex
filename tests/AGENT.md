---
title: tests — agent rules
kind: rules
layer: n/a
status: stable
owner: Juan.Kok
summary: Local rules for the test suite.
id: tests-agent
created: 2026-06-26
updated: 2026-06-26
visibility: internal
canonical: true
---
# Agent rules — `tests/`

- New or changed `src/` behavior is driven test-first (red → green → refactor).
  A public symbol without a test is unfinished.
- Once tests split by speed: `tests/unit/` mirrors `src/` 1:1 and touches no
  network/disk/process; `integration`/`e2e`/`smoke` are organized by scenario,
  named by what they exercise, not by a source file.
- The deterministic engine has a `fake` LLM backend — use it so judgment-node
  tests stay hermetic.
