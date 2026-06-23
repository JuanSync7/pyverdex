"""Deterministic-tool adapter tests (no LLM, no network)."""

from __future__ import annotations

from pathlib import Path

from pyverify.tools import adapters

REPO = Path(__file__).resolve().parents[1]
# Use a vendored tool's own source as a stable, self-contained target.
TARGET = REPO / "src" / "pyverify" / "tools" / "vendored" / "branch_mapper"


def test_run_edges_finds_cross_package_calls():
    res = adapters.run_edges(TARGET)
    assert res.ok and res.returncode == 0
    assert res.data is not None
    assert "edges" in res.data
    assert len(res.data["edges"]) > 0  # branch_mapper imports stdlib/pydantic


def test_run_branch_map_shape():
    res = adapters.run_branch_map(TARGET)
    assert res.ok and res.data is not None
    fns = res.data.get("functions", [])
    assert fns and {"module", "function_name", "total_branch_count"} <= set(fns[0])


def test_run_boundary_shape():
    res = adapters.run_boundary(TARGET)
    assert res.ok and res.data is not None
    assert "boundaries" in res.data and "internals" in res.data


def test_run_lint_ruff_clean_on_vendored():
    res = adapters.run_lint(TARGET, tools="ruff")
    assert res.ok and res.data is not None
    assert "total_issues" in res.data


def test_tool_result_semantics():
    # rc=2 -> not ok; rc=1 -> findings but ok
    from pyverify.tools.adapters import ToolResult

    assert ToolResult(tool="x", returncode=0).ok
    assert ToolResult(tool="x", returncode=1).ok
    assert ToolResult(tool="x", returncode=1).has_findings
    assert not ToolResult(tool="x", returncode=2).ok
