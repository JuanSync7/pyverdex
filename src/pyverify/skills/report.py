"""`report` subgraph — assemble + persist the unified coverage report."""

from __future__ import annotations


from langgraph.graph import END, START, StateGraph

from ..config import Config
from ..report.builder import build_unified_report, write_report
from ..state import EngineState


def build_report_graph(config: Config):
    def assemble(state: EngineState) -> dict:
        report = build_unified_report(state, config)
        paths = write_report(report, config.abs_report_dir)
        return {
            "unified_coverage": report.model_dump(mode="json"),
            "report_path": paths["html"],
            "log": [f"report: overall={report.overall_status.value} -> {paths['html']}"],
        }

    g = StateGraph(EngineState)
    g.add_node("assemble", assemble)
    g.add_edge(START, "assemble")
    g.add_edge("assemble", END)
    return g.compile()


__all__ = ["build_report_graph"]
