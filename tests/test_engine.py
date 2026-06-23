"""End-to-end engine tests on the sample project (deterministic, no LLM)."""

from __future__ import annotations

from pathlib import Path

from langgraph.types import Command

from pyverify.graph import build_engine, initial_state, make_checkpointer


def test_deterministic_run_detects_line_gap(deterministic_cfg):
    eng = build_engine(deterministic_cfg)
    state = eng.invoke(initial_state(deterministic_cfg),
                       {"configurable": {"thread_id": "t-det"}})

    uc = state["unified_coverage"]
    # classify() is only partially covered in the sample suite
    classify = next(f for f in uc["functions"] if f["function_name"] == "classify")
    assert classify["line_coverage_pct"] == 75.0
    assert classify["branch_count"] == 2

    # report artifacts written
    assert Path(state["report_path"]).exists()
    assert (Path(deterministic_cfg.abs_report_dir) / "coverage-report.json").exists()

    # no duplicated log entries (regression: nested-subgraph reducer)
    assert len(state["log"]) == len(set(state["log"]))

    # overall fails because of the real line gap
    assert uc["overall_status"] == "fail"


def test_hitl_gate_interrupt_and_resume(gated_eval_cfg):
    ck = make_checkpointer(gated_eval_cfg)
    eng = build_engine(gated_eval_cfg, checkpointer=ck)
    run_cfg = {"configurable": {"thread_id": "t-hitl"}}

    eng.invoke(initial_state(gated_eval_cfg), run_cfg)
    snap = eng.get_state(run_cfg)
    assert snap.next == ("evaluate",)  # paused at the gated stage

    payloads = [itr.value for t in snap.tasks for itr in (getattr(t, "interrupts", []) or [])]
    assert payloads and payloads[0]["stage"] == "evaluate"

    final = eng.invoke(Command(resume={"approve": True}), run_cfg)
    assert eng.get_state(run_cfg).next == ()  # finished
    assert final["approvals"]["evaluate"] == {"approve": True}
    assert "unified_coverage" in final


def test_engine_skips_disabled_stages(deterministic_cfg):
    # generate/fix/evaluate/integrate disabled -> their nodes never log
    eng = build_engine(deterministic_cfg)
    state = eng.invoke(initial_state(deterministic_cfg),
                       {"configurable": {"thread_id": "t-skip"}})
    joined = "\n".join(state["log"])
    assert "generate/" not in joined
    assert "evaluate/" not in joined
    assert "integrate/" not in joined
