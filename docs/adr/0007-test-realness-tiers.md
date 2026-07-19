---
title: Test realness tiers (mock / fake / in-process / real)
kind: adr
layer: backend
status: accepted
owner: Juan.Kok
summary: statically tier every test by its dependency-replacing signals (mocks, fakes, in-process clients, real infra; time/input controls stay neutral) and grade covered boundaries real_covered vs mock_only — demotion only on positive evidence of dependency replacement.
id: adr-0007
created: 2026-07-18
updated: 2026-07-18
visibility: public
canonical: true
---
# 0007 — Test realness tiers (Phase H2)

- **Status:** accepted
- **Date:** 2026-07-18

## Context

ADR 0006 lets the system dimension count every asserting test that exercises a
boundary. But a mocked dependency can never disagree with the code under test:
a boundary "covered" only by tests that *replace* its dependency is verified
against an assumption. The report needs to distinguish that from coverage by a
test that drove the real (or realistically substituted) dependency.

## Decision

1. **Classifier** (`skills/_realness.py`, stdlib-ast, non-vendored): every
   ``test_*`` function is tiered by its **dependency-replacing signals** —
   ``mock`` (unittest.mock/patch, pytest-mock, monkeypatch, responses, respx,
   requests-mock, vcr, …) < ``fake`` (moto, fakeredis, mongomock, pyfakefs) <
   ``in_process`` (fastapi/starlette TestClient, django/flask test clients,
   httpx ASGITransport) < ``real`` (testcontainers, docker). A test's tier is
   the **lowest** rung it touches; no signal at all → ``unknown``.
2. **Control signals are neutral, never demoting**: freezegun/time-machine,
   seeded randomness, tmp_path, caplog/capsys, parametrize. A freezegun test
   hitting a real DB is a real test — time control is not dependency
   replacement.
3. **Signals are usage-based**, gathered from (a) tiered imports actually
   referenced in the test's decorators/body, (b) direct calls
   (``patch(...)``, ``monkeypatch.setattr``), and (c) the pytest fixtures the
   test requests — resolved statically with pytest semantics: fixtures in the
   test module first, then conftest.py nearest-first up to the project root;
   fixture→fixture dependencies transitively (cycle-guarded, depth-capped);
   plugin fixtures (mocker, monkeypatch, tmp_path, …) via a declarative
   registry. Unresolvable fixtures contribute nothing.
   **Autouse fixtures are suite policy, not tier evidence**: dogfooding showed
   a single autouse harness stub (monkeypatching an internal helper for suite
   speed) demoted 162/162 of this repo's own tests to mock — zero
   discrimination. Autouse replacement signals are recorded on every test
   (``autouse:`` prefix) and rolled up as ``autouse_replacements`` — a
   suite-level caveat "real grades assume the ambient stubs don't touch your
   boundary" — but only signals a test itself uses or requests set its tier.
4. **Grading** (`report/builder.py`): a covered boundary's grade is the BEST
   tier among its asserting covering tests: ``real_covered`` when best ∈
   {in_process, real, **unknown**}, ``mock_only`` when best ∈ {mock, fake}.
   ``unknown`` grades as real-equivalent deliberately: no dependency-replacing
   signal means whatever the test touched ran **unreplaced** — demotion to
   mock_only requires positive evidence of replacement, absence of proof of
   containers is not proof of mocking. Grading only happens when per-test
   contexts exist (ADR 0006); the engine-only fallback stays Phase G
   bit-for-bit, and engine-lifted boundaries with no attributed asserting
   test stay ungraded ``covered`` (no data is not mock evidence).
5. **Report**: ``boundaries_real_covered`` / ``boundaries_mock_only`` /
   ``boundary_realness_pct`` (real-covered / total; None when ungradable);
   headline leads with the real-tested ratio; ``mock_only_sample`` is the new
   worklist (feeds Phase L's ``boundary_mock_only`` gap type). Toggle
   ``audit.realness`` (default on).

## Consequences

- The mock-vs-real blind spot (user points 1/2) is measured: per boundary,
  the report now says *covered against what*.
- Known v1 limitations, deliberate: static heuristics (dynamic fixture
  registration, ``request.getfixturevalue`` and plugin fixtures outside the
  registry are invisible); live connection strings are not yet a ``real``
  signal; per-boundary (rather than per-test) mock targeting is not analyzed —
  a test may mock dependency A while hitting boundary B for real and still
  read as mock-tier for B; test files with the same stem in different
  directories share a ``test_id`` key (same last-two-segments ambiguity as the
  ADR 0006 label join); class-based test methods produce a label whose second
  segment is the class name, so they miss the stem+function join and stay
  ungraded (zero class-based tests exist in this repo today). All bias toward
  *under*-claiming realness except the ``unknown``→real rule, whose rationale
  is above.
