"""Unit tests for the unified report merge (synthetic state, no tools run)."""

from __future__ import annotations

from pyverdex.config import Config
from pyverdex.models import DimensionStatus
from pyverdex.report.builder import build_unified_report


def _state() -> dict:
    return {
        "project_root": "/p", "source_root": "/p/src", "test_root": "/p/tests",
        "coverage_report": {
            "total_functions": 2,
            "gaps": [
                {"module": "m.a", "function_name": "f", "line_start": 1, "line_end": 9,
                 "coverage_pct": 60.0, "missing_lines": [3, 4], "is_boundary": True},
            ],
        },
        "edge_report": {"edges": [
            {"caller_module": "m.a", "callee_module": "ext.b", "call_site_line": 5}],
            "new_edges": []},
        "branch_map": {"functions": [
            {"module": "m.a", "function_name": "f", "line_start": 1, "line_end": 9,
             "total_branch_count": 3, "branches": [1, 2, 3]}]},
        "assertion_report": {"scores": [
            {"test_file": "t.py", "test_function": "test_f", "quality_score": 0.2,
             "assertion_count": 1, "issues": ["trivial_assertion"]}]},
        "generated": [
            {"module": "m.a", "function_name": "f", "mutation_kill_rate": 1.0,
             "mutation_survivors": 0}],
        "lint_report": {"total_issues": 0, "total_errors": 0},
    }


def test_merge_all_dimensions():
    r = build_unified_report(_state(), Config())
    # boundary function => critical tier, target 95, 60% => fail
    f = next(f for f in r.functions if f.function_name == "f")
    assert f.tier == "critical"
    assert f.line_coverage_pct == 60.0
    assert f.line_status is DimensionStatus.failed
    assert f.branch_count == 3
    assert f.mutation_kill_rate == 1.0

    assert r.cross_package_edges == 1
    assert r.boundary_gaps == 1
    assert r.weak_tests == 1  # quality 0.2 < 0.5
    # any failing dimension => overall fail
    assert r.overall_status is DimensionStatus.failed

    dim_names = {d.name for d in r.dimensions}
    assert "line" in dim_names
    assert any("edge" in n for n in dim_names)
    assert "mutation" in dim_names


def test_line_not_run_without_coverage():
    st = _state()
    st["coverage_report"] = {}
    r = build_unified_report(st, Config())
    line = next(d for d in r.dimensions if d.name == "line")
    assert line.status is DimensionStatus.not_run


def test_whole_codebase_headline_distinct_from_gap_avg():
    """The headline must be whole-codebase coverage, not the gap-function average.

    Here the only gap function sits at 60%, but the codebase as a whole is 92%
    — the report must lead with 92% and keep 60% as the labelled secondary stat.
    """
    st = _state()
    st["coverage_totals"] = {
        "line": {"covered": 92, "executable": 100, "pct": 92.0},
        "branch": {"covered": 8, "total": 10, "pct": 80.0},
    }
    r = build_unified_report(st, Config())

    assert r.whole_line_coverage_pct == 92.0
    assert r.whole_branch_coverage_pct == 80.0
    assert r.covered_lines == 92 and r.executable_lines == 100
    # legacy gap-function average is preserved, but distinct
    assert r.overall_line_coverage_pct == 60.0

    line_dim = next(d for d in r.dimensions if d.name == "line")
    assert "92.0% line coverage (whole codebase)" in line_dim.headline
    assert line_dim.detail["gap_function_avg_pct"] == 60.0
    assert line_dim.detail["whole_codebase_pct"] == 92.0

    branch_dim = next(d for d in r.dimensions if d.name == "branch")
    assert "80.0% branch coverage (whole codebase)" in branch_dim.headline


def test_cold_tier_relaxes_gate_when_configured():
    """A cold-path function uses the 70% target, so 75% passes the gate that a
    standard (85%) function would fail — proving the cold tier is wired."""
    st = _state()
    st["coverage_report"] = {
        "total_functions": 1,
        "gaps": [{"module": "pkg._internal.helpers", "function_name": "h",
                  "line_start": 1, "line_end": 5, "coverage_pct": 75.0,
                  "missing_lines": [3], "is_boundary": False}],
    }
    cfg = Config(thresholds={"cold_paths": ["_internal"]})
    f = next(f for f in build_unified_report(st, cfg).functions if f.function_name == "h")
    assert f.tier == "cold"
    assert f.line_target == 70.0
    assert f.line_status is DimensionStatus.warn  # 75% >= 70% cold target => not failed

    # without the cold path it would be standard (85%) and fail
    f2 = next(f for f in build_unified_report(st, Config()).functions if f.function_name == "h")
    assert f2.tier == "standard"
    assert f2.line_status is DimensionStatus.failed


def test_smoke_dimension_pass_and_fail():
    """The smoke (imports) dimension mirrors the audit import-sweep: pass when
    every module imports, fail (listing failures) when one doesn't."""
    clean = _state()
    clean["smoke_report"] = {"total": 5, "imported": 5, "failures": []}
    r = build_unified_report(clean, Config())
    d = next(d for d in r.dimensions if d.name == "smoke (imports)")
    assert d.status is DimensionStatus.passed
    assert "5/5 source modules import cleanly" in d.headline
    assert r.smoke_modules_imported == 5 and r.smoke_modules_total == 5

    broken = _state()
    broken["smoke_report"] = {"total": 5, "imported": 4,
                              "failures": [{"module": "pkg.bad", "error": "ImportError: x"}]}
    r2 = build_unified_report(broken, Config())
    d2 = next(d for d in r2.dimensions if d.name == "smoke (imports)")
    assert d2.status is DimensionStatus.failed
    assert "1 fail to import" in d2.headline
    assert d2.detail["failures"] == ["pkg.bad"]
    assert r2.overall_status is DimensionStatus.failed  # a failing dim fails overall


def test_test_levels_dimension_counts_and_tags_function():
    """A unit record tags its function's test_level and feeds the by-level count;
    an integration record is counted too but tracked via the integration dim."""
    st = _state()
    st["generated"] = [
        {"module": "m.a", "function_name": "f", "mutation_kill_rate": 1.0,
         "mutation_survivors": 0, "test_level": "unit"},
        {"module": "m.api", "boundary_fn": "handler", "test_path": "/t/a.py",
         "gate": "pass", "test_level": "integration"},
    ]
    r = build_unified_report(st, Config())

    assert r.tests_by_level == {"unit": 1, "integration": 1}
    dim = next(d for d in r.dimensions if d.name == "test-levels")
    assert dim.status is DimensionStatus.passed
    assert dim.detail["by_level"] == {"unit": 1, "integration": 1}
    # the unit record tagged its per-function view
    f = next(f for f in r.functions if f.function_name == "f")
    assert f.test_level == "unit"


def test_no_test_levels_dimension_without_tagged_records():
    r = build_unified_report(_state(), Config())  # generated records carry no level
    assert r.tests_by_level == {}
    assert not any(d.name == "test-levels" for d in r.dimensions)
    assert not any(d.name == "smoke (imports)" for d in r.dimensions)


def test_integration_dimension_counts_and_isolates():
    """The integration dimension counts only WRITTEN integrate records (boundary_fn
    + test_path), every gate outcome shows in by_gate, and integrate records never
    pollute the per-function (mutation) view."""
    st = _state()
    st["generated"] = [
        {"module": "m.api", "boundary_fn": "handler", "test_path": "/t/a.py", "gate": "pass"},
        {"module": "m.db", "boundary_fn": "save", "test_path": "/t/b.py",
         "gate": "secret-found", "secrets": ["aws_access_key"]},
        {"module": "m.q", "boundary_fn": "enqueue", "test_path": "/t/c.py", "gate": "red"},
        # propose-only integrate record (boundary_fn but NO test_path) => excluded
        {"module": "m.x", "boundary_fn": "y", "proposed_test": "..."},
        # a generate record (function_name, not boundary_fn) => excluded from integration
        {"module": "m.a", "function_name": "f", "mutation_kill_rate": 1.0},
    ]
    r = build_unified_report(st, Config())

    assert r.integration_tests_written == 3   # only the boundary_fn + test_path rows
    assert r.integration_tests_passed == 1
    dim = next(d for d in r.dimensions if d.name.startswith("integration"))
    assert dim.status is DimensionStatus.failed  # 2 of 3 failed
    assert dim.detail["by_gate"] == {"pass": 1, "secret-found": 1, "red": 1}
    # the generate record still merges into its function, not the integration count
    assert next(f for f in r.functions if f.function_name == "f").mutation_kill_rate == 1.0
