---
title: Tests
kind: tests
layer: n/a
status: stable
owner: Juan.Kok
summary: The Python test suite. Migrating to unit (mirrors src/) + integration/e2e/smoke by scenario.
id: tests-readme
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# `tests/`

The pytest suite for the engine (`test_engine`, `test_adapters`,
`test_apply_mode`, `test_config`, `test_discovery`, `test_report_builder`,
`test_server`). Run with `make test` (`uv run pytest`).

Under the [Keel migration](../docs/adr/0001-adopt-project-keel-structure.md)
these split into `tests/unit/` (fast, isolated, **mirrors `src/`**) plus
`tests/integration/`, `tests/e2e/`, and `tests/smoke/`, organized by scenario.
Test plans and the coverage register move to `../test-docs/`.
