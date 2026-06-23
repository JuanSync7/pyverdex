"""`lint` subgraph — the static-analysis stage (deterministic).

Mirrors the test-lint SKILL.md flowchart:
``[SCAN] -> [RUN-LINTERS] -> [AGGREGATE] -> [EMIT]``. Runs the vendored
``lint_reporter`` (ruff + mypy + bandit + vulture) over the source root and
records a LintReport. Classifies only — never fails the build on findings.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..config import Config
from ..state import EngineState
from ..tools import adapters


def build_lint_graph(config: Config):
    def run_linters(state: EngineState) -> dict:
        source = Path(state["source_root"])
        res = adapters.run_lint(source)
        if not res.ok:
            return {
                "errors": [f"lint: tool error rc={res.returncode} {res.stderr[:200]}"],
                "log": ["lint: linter could not run"],
            }
        report = res.data or {}
        total = report.get("total_issues", 0)
        errs = report.get("total_errors", 0)
        return {
            "lint_report": report,
            "log": [f"lint: {total} issues ({errs} errors) across "
                    f"{len(report.get('summaries', []))} tools"],
        }

    def emit(state: EngineState) -> dict:
        # lint never hard-gates; findings are surfaced to fix/audit downstream
        return {"log": ["lint: report emitted -> lint_report"]}

    g = StateGraph(EngineState)
    g.add_node("run_linters", run_linters)
    g.add_node("emit", emit)
    g.add_edge(START, "run_linters")
    g.add_edge("run_linters", "emit")
    g.add_edge("emit", END)
    return g.compile()


__all__ = ["build_lint_graph"]
