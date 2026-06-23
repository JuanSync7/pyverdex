"""Unit tests for the unified report merge (synthetic state, no tools run)."""

from __future__ import annotations

from pyverify.config import Config
from pyverify.models import DimensionStatus
from pyverify.report.builder import build_unified_report


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
