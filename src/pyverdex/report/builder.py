"""Build the unified, multi-dimensional coverage report from engine state.

This is the "proper test coverage" output: it merges every dimension that has
real data — line (coverage.py), branch (branch_mapper), edge/call-graph
(coverage_analyzer --edges), mutation kill-rate (mutation_runner, when the
generate stage ran it), and assertion-quality (assertion_quality) — into a
single per-function table plus dimension rollups and an overall verdict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import Config
from ..models import (
    DimensionRollup,
    DimensionStatus,
    EdgeRecord,
    FunctionCoverage,
    TestQualityRecord,
    UnifiedCoverageReport,
)
from ..state import EngineState

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _key(module: str, fn: str) -> str:
    return f"{module}::{fn}"


def build_unified_report(state: EngineState, config: Config) -> UnifiedCoverageReport:
    thresholds = config.thresholds
    coverage = state.get("coverage_report") or {}
    edges_data = state.get("edge_report") or {}
    branch = state.get("branch_map") or {}
    assertion = state.get("assertion_report") or {}
    generated = state.get("generated") or []

    funcs: dict[str, FunctionCoverage] = {}

    # --- line dimension (gaps only list functions below 100%) -------------
    for g in coverage.get("gaps", []):
        is_boundary = bool(g.get("is_boundary"))
        tier = thresholds.tier_for(is_boundary=is_boundary, module=g.get("module", ""))
        target = thresholds.line_target(tier)
        pct = float(g.get("coverage_pct", 0.0))
        k = _key(g.get("module", "?"), g.get("function_name", "?"))
        funcs[k] = FunctionCoverage(
            module=g.get("module", "?"),
            function_name=g.get("function_name", "?"),
            line_start=int(g.get("line_start", 0)),
            line_end=int(g.get("line_end", 0)),
            tier=tier,
            is_boundary=is_boundary,
            line_coverage_pct=pct,
            missing_lines=list(g.get("missing_lines", [])),
            line_target=target,
            line_status=DimensionStatus.failed if pct < target else DimensionStatus.warn,
        )

    # --- branch dimension (structural enumeration per function) ----------
    for f in branch.get("functions", []):
        mod = f.get("module") or branch.get("source_root", "?")
        name = f.get("function_name", "?")
        branches = f.get("branches")
        count = f.get("total_branch_count")
        if count is None and isinstance(branches, list):
            count = len(branches)
        k = _key(mod, name)
        if k in funcs:
            funcs[k].branch_count = count
        else:
            funcs[k] = FunctionCoverage(
                module=mod, function_name=name, branch_count=count,
                line_start=int(f.get("line_start", 0)), line_end=int(f.get("line_end", 0)),
            )

    # --- mutation dimension (from generate stage, if any) ----------------
    for rec in generated:
        mod = rec.get("module", "?")
        name = rec.get("function_name") or rec.get("function", "?")
        kr = rec.get("mutation_kill_rate")
        k = _key(mod, name)
        if k in funcs and kr is not None:
            funcs[k].mutation_kill_rate = kr
            funcs[k].mutation_survivors = rec.get("mutation_survivors")

    # --- assertion / test-quality dimension ------------------------------
    test_quality: list[TestQualityRecord] = []
    for t in assertion.get("scores", []):
        tid = (f"{t.get('test_file')}::{t.get('test_function')}"
               if t.get("test_function") else t.get("test_id", "?"))
        test_quality.append(TestQualityRecord(
            test_id=tid,
            score=float(t.get("quality_score", t.get("score", 0.0))),
            assertion_count=int(t.get("assertion_count", 0)),
            issues=[i.get("kind", str(i)) if isinstance(i, dict) else str(i)
                    for i in (t.get("issues") or [])],
        ))

    edges = [
        EdgeRecord(
            caller_module=e.get("caller_module", "?"),
            callee_module=e.get("callee_module", "?"),
            call_site_line=e.get("call_site_line"),
        )
        for e in edges_data.get("edges", [])
    ]

    # --- headline metrics + dimension rollups ----------------------------
    # whole-codebase coverage (the honest number) comes from coverage.py totals;
    # the gap-function average below is a secondary, clearly-labelled stat.
    totals = state.get("coverage_totals") or {}
    totals_line = totals.get("line") or {}
    totals_branch = totals.get("branch") or {}
    whole_line = totals_line.get("pct")
    whole_branch = totals_branch.get("pct")
    covered_lines = totals_line.get("covered")
    executable_lines = totals_line.get("executable")

    line_pcts = [f.line_coverage_pct for f in funcs.values() if f.line_coverage_pct is not None]
    overall_line = round(sum(line_pcts) / len(line_pcts), 2) if line_pcts else None
    line_gaps = sum(1 for f in funcs.values()
                    if f.line_status in (DimensionStatus.failed, DimensionStatus.warn))
    boundary_gaps = sum(1 for f in funcs.values()
                        if f.is_boundary and f.line_status == DimensionStatus.failed)
    kill_rates = [f.mutation_kill_rate for f in funcs.values()
                  if f.mutation_kill_rate is not None]
    overall_kill = round(sum(kill_rates) / len(kill_rates), 3) if kill_rates else None
    weak_tests = sum(1 for t in test_quality if t.score < thresholds.assertion_score)

    dims: list[DimensionRollup] = []
    if coverage:
        below = sum(1 for f in funcs.values() if f.line_status == DimensionStatus.failed)
        if whole_line is not None:
            head = (f"{whole_line}% line coverage (whole codebase); "
                    f"{below} below tier target")
        elif overall_line is not None:
            head = f"{overall_line}% avg over gap functions; {below} below tier target"
        else:
            head = "no line data"
        dims.append(DimensionRollup(
            name="line",
            status=DimensionStatus.failed if below else DimensionStatus.passed,
            headline=head,
            detail={"whole_codebase_pct": whole_line,
                    "gap_function_avg_pct": overall_line,
                    "functions_with_gaps": line_gaps, "boundary_gaps": boundary_gaps},
        ))
    else:
        dims.append(DimensionRollup(name="line", status=DimensionStatus.not_run,
                                    headline="no .coverage data (target had no runnable tests?)"))

    dims.append(DimensionRollup(
        name="edge (function-to-function)",
        status=DimensionStatus.passed if edges else DimensionStatus.not_run,
        headline=f"{len(edges)} cross-package call edges mapped",
        detail={"edges": len(edges), "new_edges": len(edges_data.get("new_edges", []))},
    ))
    branch_mapped = len(branch.get("functions", []))
    dims.append(DimensionRollup(
        name="branch",
        status=(DimensionStatus.passed if (whole_branch is not None or branch_mapped)
                else DimensionStatus.not_run),
        headline=(f"{whole_branch}% branch coverage (whole codebase); "
                  f"{branch_mapped} functions branch-mapped"
                  if whole_branch is not None
                  else f"{branch_mapped} functions branch-mapped"),
        detail={"whole_codebase_pct": whole_branch, "functions_branch_mapped": branch_mapped},
    ))
    dims.append(DimensionRollup(
        name="mutation",
        status=(DimensionStatus.not_run if overall_kill is None
                else DimensionStatus.passed if overall_kill >= thresholds.mutation_kill_rate
                else DimensionStatus.failed),
        headline=("not run (generate stage produces this)" if overall_kill is None
                  else f"{overall_kill:.0%} kill-rate over {len(kill_rates)} functions"),
    ))
    dims.append(DimensionRollup(
        name="assertion-quality",
        status=(DimensionStatus.not_run if not test_quality
                else DimensionStatus.failed if weak_tests else DimensionStatus.passed),
        headline=(f"{weak_tests}/{len(test_quality)} tests below {thresholds.assertion_score}"
                  if test_quality else "not run"),
    ))
    # --- integration dimension (real-service tests written by integrate apply) --
    int_records = [r for r in generated if "boundary_fn" in r and r.get("test_path")]
    int_written = len(int_records)
    int_passed = sum(1 for r in int_records if r.get("gate") == "pass")
    if int_records:
        int_secret = sum(1 for r in int_records if r.get("gate") == "secret-found")
        int_flaky = sum(1 for r in int_records if r.get("gate") == "flaky")
        failed = int_written - int_passed
        dims.append(DimensionRollup(
            name="integration (real-service)",
            status=DimensionStatus.passed if failed == 0 else DimensionStatus.failed,
            headline=(f"{int_passed}/{int_written} real-service tests pass"
                      + (f"; {int_secret} leaked secrets, {int_flaky} flaky" if failed else "")),
            detail={"written": int_written, "passed": int_passed,
                    "secret_found": int_secret, "flaky": int_flaky},
        ))
    if state.get("lint_report"):
        lr = state["lint_report"]
        dims.append(DimensionRollup(
            name="lint/static",
            status=DimensionStatus.failed if lr.get("total_errors") else DimensionStatus.passed,
            headline=f"{lr.get('total_issues', 0)} issues, {lr.get('total_errors', 0)} errors",
        ))

    # overall: fail if any dimension failed, warn if any not_run, else pass
    statuses = [d.status for d in dims]
    if DimensionStatus.failed in statuses:
        overall = DimensionStatus.failed
    elif all(s == DimensionStatus.not_run for s in statuses):
        overall = DimensionStatus.unknown
    elif DimensionStatus.not_run in statuses:
        overall = DimensionStatus.warn
    else:
        overall = DimensionStatus.passed

    return UnifiedCoverageReport(
        project_root=state["project_root"],
        source_root=state["source_root"],
        test_root=state["test_root"],
        generated_at=datetime.now(tz=timezone.utc),
        functions=sorted(funcs.values(), key=lambda f: (f.line_coverage_pct or 101, f.module)),
        edges=edges,
        test_quality=test_quality,
        dimensions=dims,
        total_functions=coverage.get("total_functions", len(funcs)),
        functions_with_line_gaps=line_gaps,
        boundary_gaps=boundary_gaps,
        whole_line_coverage_pct=whole_line,
        whole_branch_coverage_pct=whole_branch,
        covered_lines=covered_lines,
        executable_lines=executable_lines,
        overall_line_coverage_pct=overall_line,
        cross_package_edges=len(edges),
        integration_tests_written=int_written,
        integration_tests_passed=int_passed,
        mutation_kill_rate=overall_kill,
        weak_tests=weak_tests,
        overall_status=overall,
    )


def render_html(report: UnifiedCoverageReport) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("report.html.j2").render(r=report)


def write_report(report: UnifiedCoverageReport, report_dir: Path) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "coverage-report.json"
    html_path = report_dir / "coverage-report.html"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return {"json": str(json_path), "html": str(html_path)}


__all__ = ["build_unified_report", "render_html", "write_report"]
