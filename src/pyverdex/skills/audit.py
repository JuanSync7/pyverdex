"""`audit` subgraph — the multi-dimensional measurement core (deterministic).

Mirrors the test-audit SKILL.md flowchart, condensed to the dimensions that
have a *real* vendored tool behind them:

``[COLLECT] -> [SNAPSHOT] -> [SCORE] -> [EMIT]``

- COLLECT: run the target test suite under coverage.py (best-effort) to make
  a ``.coverage`` data file.
- SNAPSHOT: line gaps (coverage_analyzer), cross-package call-graph edges
  (coverage_analyzer --edges), structural branches (branch_mapper), boundary
  classification (boundary_classifier), assertion quality (assertion_quality),
  log-path coverage (log_contract_validator).
- SCORE: derive actionable gaps + tiers, decide whether coverage targets are
  met (drives the audit⇄generate loop), rank modules by priority.

The original skill also referenced critical_scorer / gaming_detector /
dep_vulnerability tools that were never implemented upstream; those dimensions
are intentionally omitted rather than faked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..config import Config
from ..models import AuditGapReport, CoverageGapRecord, CoverageState, ModuleCoverage
from ..state import EngineState
from ..tools import adapters


def build_audit_graph(config: Config):
    thresholds = config.thresholds

    def collect(state: EngineState) -> dict:
        root = Path(state["project_root"])
        source = Path(state["source_root"])
        test = Path(state["test_root"])
        if not test.exists():
            return {"log": [f"audit/collect: no test root at {test}; "
                            "line coverage will be unavailable"]}
        res = adapters.collect_coverage(root, source, test)
        msg = (f"audit/collect: coverage run rc={res.returncode}"
               + (" (timed out)" if res.timed_out else ""))
        return {"log": [msg]}

    def snapshot(state: EngineState) -> dict:
        source = Path(state["source_root"])
        root = Path(state["project_root"])
        test = Path(state["test_root"])
        out: dict = {"log": []}

        # smoke: does every source module import? (the fast, no-LLM 'smoke' signal)
        if config.audit.import_smoke and source.exists():
            sm = adapters.run_import_smoke(
                source, root, timeout=config.audit.import_smoke_timeout)
            if sm.ok and sm.data is not None:
                out["smoke_report"] = sm.data
                out["log"].append(
                    f"audit/snapshot: import smoke {sm.data.get('imported')}/"
                    f"{sm.data.get('total')} modules import cleanly")
            else:
                out["log"].append("audit/snapshot: import smoke unavailable "
                                  f"({sm.stderr[:120] or sm.parse_error})")

        gaps = adapters.run_coverage_gaps(root, source)
        if gaps.ok and gaps.data is not None:
            out["coverage_report"] = gaps.data
            out["log"].append(
                f"audit/snapshot: line coverage on {gaps.data.get('total_functions', 0)} "
                f"functions, {gaps.data.get('functions_with_gaps', 0)} with gaps")
        else:
            out["log"].append("audit/snapshot: line coverage unavailable "
                              f"({gaps.stderr[:120] or gaps.parse_error})")

        totals = adapters.coverage_totals(root, source)
        if totals.ok and totals.data is not None:
            out["coverage_totals"] = totals.data
            line = totals.data.get("line", {})
            branch = totals.data.get("branch")
            msg = (f"audit/snapshot: whole-codebase line {line.get('pct')}% "
                   f"({line.get('covered')}/{line.get('executable')} lines)")
            if branch:
                msg += f", branch {branch.get('pct')}% ({branch.get('covered')}/{branch.get('total')})"
            out["log"].append(msg)

        edges = adapters.run_edges(source, test_path=str(test))
        if edges.ok and edges.data is not None:
            out["edge_report"] = edges.data
            out["log"].append(
                f"audit/snapshot: {len(edges.data.get('edges', []))} cross-package edges")

        bm = adapters.run_branch_map(source)
        if bm.ok and bm.data is not None:
            out["branch_map"] = bm.data

        bd = adapters.run_boundary(source)
        if bd.ok and bd.data is not None:
            out["boundary_report"] = bd.data

        if test.exists():
            aq = adapters.run_assertion_quality(
                test, threshold=thresholds.assertion_score,
                min_assertions=thresholds.assertion_min)
            if aq.data is not None:
                out["assertion_report"] = aq.data

            lc = adapters.run_log_contract(source)
            if lc.ok and lc.data is not None:
                out["log_contract_report"] = lc.data
        return out

    def score(state: EngineState) -> dict:
        report = state.get("coverage_report") or {}
        raw_gaps = report.get("gaps", [])
        records: list[CoverageGapRecord] = []
        below_target = 0
        module_worst: dict[str, float] = {}
        critical_modules: set[str] = set()

        for g in raw_gaps:
            is_boundary = bool(g.get("is_boundary"))
            tier = thresholds.tier_for(is_boundary=is_boundary, module=g.get("module", ""))
            target = thresholds.line_target(tier)
            pct = float(g.get("coverage_pct", 0.0))
            is_below = pct < target
            reason = (f"line {pct:.0f}% < {target:.0f}% ({tier})"
                      if is_below else "uncovered lines in covered function")
            if is_below:
                below_target += 1
            records.append(CoverageGapRecord(
                module=g.get("module", "?"),
                function_name=g.get("function_name", "?"),
                line_start=int(g.get("line_start", 0)),
                line_end=int(g.get("line_end", 0)),
                coverage_pct=pct,
                missing_lines=list(g.get("missing_lines", [])),
                is_boundary=is_boundary,
                tier=tier,
                reason=reason,
            ))
            mod = g.get("module", "?")
            module_worst[mod] = min(module_worst.get(mod, 100.0), pct)
            if is_boundary and is_below:
                critical_modules.add(mod)

        ranking = [m for m, _ in sorted(module_worst.items(), key=lambda kv: kv[1])]
        gap_report = AuditGapReport(
            priority_ranking=ranking,
            critical_modules=sorted(critical_modules),
            gaps=records,
        )

        # Loop control: targets are "met" when nothing is below its tier target.
        # If there is no line data at all, we cannot drive the loop, so we
        # treat it as met (and the report node will mark the dimension not_run).
        has_line_data = bool(report)
        coverage_met = (below_target == 0)

        cov_state = CoverageState(
            generated_at=datetime.now(tz=timezone.utc),
            project_root=state["project_root"],
            modules={
                m: ModuleCoverage(module_path=m, criticality_score=1.0 if m in critical_modules else 0.0)
                for m in module_worst
            },
            audit_gap_report=gap_report,
        )
        return {
            "audit_gap_report": gap_report.model_dump(mode="json"),
            "coverage_state": cov_state.model_dump(mode="json"),
            "coverage_met": coverage_met,
            "log": [f"audit/score: {len(records)} gaps, {below_target} below target, "
                    f"{len(critical_modules)} critical modules, "
                    f"targets_met={coverage_met}, line_data={has_line_data}"],
        }

    g = StateGraph(EngineState)
    g.add_node("collect", collect)
    g.add_node("snapshot", snapshot)
    g.add_node("score", score)
    g.add_edge(START, "collect")
    g.add_edge("collect", "snapshot")
    g.add_edge("snapshot", "score")
    g.add_edge("score", END)
    return g.compile()


__all__ = ["build_audit_graph"]
