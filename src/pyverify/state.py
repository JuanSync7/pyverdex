"""The LangGraph engine state.

A ``TypedDict`` (total=False) so every node returns a partial update that
LangGraph merges in. ``log`` and ``errors`` accumulate across nodes via an
``operator.add`` reducer; every other key is last-write-wins.

Payloads (lint report, coverage report, gap report, …) are stored as plain
dicts — the JSON the tools emit or the ``model_dump()`` of an engine model —
so the whole state stays JSON/checkpoint serialisable.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional, TypedDict


def _accumulate(left: list[str], right: list[str]) -> list[str]:
    """Reducer for log/errors that is safe across nested subgraphs.

    A plain ``operator.add`` double-counts here: a compiled subgraph shares
    these channels, so it returns the *cumulative* list (inherited + its own
    additions), which the parent would then add again. This reducer detects
    that case — when ``right`` already starts with ``left`` it is a cumulative
    subgraph output (take it as-is); otherwise ``right`` is a plain node delta
    (append it).
    """
    left = left or []
    right = right or []
    if right[: len(left)] == left:
        return list(right)
    return [*left, *right]


class EngineState(TypedDict, total=False):
    # --- inputs / context -------------------------------------------------
    project_root: str
    source_root: str
    test_root: str

    # --- per-stage artifacts (dicts) -------------------------------------
    lint_report: dict[str, Any]
    fix_report: dict[str, Any]
    coverage_report: dict[str, Any]  # CoverageReport (line gaps)
    edge_report: dict[str, Any]  # EdgeCoverageReport (call-graph edges)
    branch_map: dict[str, Any]
    boundary_report: dict[str, Any]
    assertion_report: dict[str, Any]
    log_contract_report: dict[str, Any]
    audit_gap_report: dict[str, Any]  # AuditGapReport
    coverage_state: dict[str, Any]  # CoverageState
    integration_strategies: list[dict[str, Any]]
    generated: list[dict[str, Any]]  # finalized per-gap generation results
    gen_pending: list[dict[str, Any]]  # this cycle's authored-but-not-applied tests
    gen_handled: list[str]  # "module::fn" already authored (don't re-author in loop)

    # --- unified output ---------------------------------------------------
    unified_coverage: dict[str, Any]  # UnifiedCoverageReport
    report_path: Optional[str]

    # --- loop / control ---------------------------------------------------
    cycle: int  # audit→generate loop counter
    coverage_met: bool  # set by audit when targets satisfied
    loop_exhausted: bool  # set by generate when it has no further work this run
    pending_gate: Optional[dict[str, Any]]  # interrupt payload awaiting approval
    approvals: dict[str, Any]  # stage -> decision

    # --- accumulators -----------------------------------------------------
    log: Annotated[list[str], _accumulate]
    errors: Annotated[list[str], _accumulate]


__all__ = ["EngineState"]
