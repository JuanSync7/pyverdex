"""Top-level engine graph: wires the skill subgraphs into one StateGraph.

Flow (stages present only when enabled in config; audit + report always):

    START -> lint -> fix -> audit -> [generate -> audit]* -> evaluate
          -> integrate -> report -> END

The ``generate -> audit`` self-loop continues while coverage targets are unmet,
the cycle cap is not hit, and generate still has work; otherwise control falls
through to evaluate/integrate/report. Human gates inside fix/generate/evaluate/
integrate raise ``interrupt()`` (per-stage config toggle) and are resumed via a
checkpointer + ``Command(resume=...)``.
"""

from __future__ import annotations

import sqlite3

from langgraph.graph import END, START, StateGraph

from .backends import get_backend
from .config import Config, StageName
from .skills.audit import build_audit_graph
from .skills.evaluate import build_evaluate_graph
from .skills.fix import build_fix_graph
from .skills.generate import build_generate_graph
from .skills.integrate import build_integrate_graph
from .skills.lint import build_lint_graph
from .skills.report import build_report_graph
from .state import EngineState


def _post_audit_entry(config: Config) -> str:
    if config.is_enabled(StageName.evaluate):
        return "evaluate"
    if config.is_enabled(StageName.integrate):
        return "integrate"
    return "report"


def build_engine(config: Config, checkpointer=None, backend=None):
    g = StateGraph(EngineState)

    # One memory-carrying LLM backend per run, shared across judgment nodes.
    if backend is None:
        backend = get_backend(config)

    lint_on = config.is_enabled(StageName.lint)
    fix_on = lint_on and config.is_enabled(StageName.fix)
    gen_on = config.is_enabled(StageName.generate)
    eval_on = config.is_enabled(StageName.evaluate)
    integ_on = config.is_enabled(StageName.integrate)
    max_cycles = config.loop.max_cycles

    # --- nodes (subgraphs) ------------------------------------------------
    if lint_on:
        g.add_node("lint", build_lint_graph(config))
    if fix_on:
        g.add_node("fix", build_fix_graph(config, backend))
    g.add_node("audit", build_audit_graph(config))
    if gen_on:
        g.add_node("generate", build_generate_graph(config, backend))
    if eval_on:
        g.add_node("evaluate", build_evaluate_graph(config))
    if integ_on:
        g.add_node("integrate", build_integrate_graph(config, backend))
    g.add_node("report", build_report_graph(config))

    # --- pre-audit chain --------------------------------------------------
    if lint_on:
        g.add_edge(START, "lint")
        g.add_edge("lint", "fix" if fix_on else "audit")
        if fix_on:
            g.add_edge("fix", "audit")
    else:
        g.add_edge(START, "audit")

    # --- audit -> generate loop OR fall through ---------------------------
    def after_audit(state: EngineState) -> str:
        if (gen_on and not state.get("coverage_met")
                and state.get("cycle", 0) < max_cycles
                and not state.get("loop_exhausted")):
            return "generate"
        return _post_audit_entry(config)

    targets = {"report": "report"}
    if gen_on:
        targets["generate"] = "generate"
    if eval_on:
        targets["evaluate"] = "evaluate"
    if integ_on:
        targets["integrate"] = "integrate"
    g.add_conditional_edges("audit", after_audit, targets)

    if gen_on:
        g.add_edge("generate", "audit")  # re-measure after authoring

    # --- post-audit chain -------------------------------------------------
    if eval_on:
        g.add_edge("evaluate", "integrate" if integ_on else "report")
    if integ_on:
        g.add_edge("integrate", "report")
    g.add_edge("report", END)

    return g.compile(checkpointer=checkpointer)


def make_checkpointer(config: Config):
    """File-backed SQLite checkpointer (enables interrupt/resume across runs)."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    db = config.abs_checkpoint_db
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def initial_state(config: Config) -> EngineState:
    return EngineState(
        project_root=str(config.root),
        source_root=str(config.abs_source_root),
        test_root=str(config.abs_test_root),
        cycle=0,
        generated=[],
        gen_pending=[],
        int_pending=[],
        gen_handled=[],
        integration_strategies=[],
        approvals={},
        log=[],
        errors=[],
    )


__all__ = ["build_engine", "make_checkpointer", "initial_state"]
