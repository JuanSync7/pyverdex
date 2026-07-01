"""`evaluate` subgraph — decide what needs real integration (deterministic).

Mirrors test-evaluate: classify boundaries, score mock-replacement value with
``score = tier_weight * risk_weight * coverage_gap``, and pick a lifecycle
pattern per candidate. Boundary classification reuses the audit snapshot
(boundary_classifier). The original ``mock_inventory`` tool was never
implemented upstream, so candidates are derived from boundary functions that
still carry line gaps rather than from a mock inventory.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..config import Config, StageName
from ..state import EngineState
from ._detect import CATEGORY_PATTERN as _PATTERN
from ._detect import detect_boundary, detect_framework
from ._gates import human_gate

_RISK = {"db": 5, "api": 4, "queue": 3, "file": 2, "cli": 1}


def _category(module: str) -> str:
    m = module.lower()
    if any(k in m for k in ("db", "sql", "repo", "model", "orm")):
        return "db"
    if any(k in m for k in ("queue", "celery", "broker", "kafka", "task")):
        return "queue"
    if any(k in m for k in ("file", "fs", "storage", "path", "io")):
        return "file"
    if any(k in m for k in ("cli", "cmd", "console")):
        return "cli"
    return "api"


def _classify(module: str, source_root: Path) -> tuple[str, str]:
    """(category, lifecycle_pattern): semantic detection first (with per-framework
    pattern refinement), the filename heuristic + category-default as fallback."""
    detected = detect_boundary(module, source_root)
    if detected is not None:
        return detected
    cat = _category(module)
    return cat, _PATTERN[cat]


def _classify_category(module: str, source_root: Path) -> str:
    """Semantic (import-based) category first, filename heuristic as fallback."""
    return detect_framework(module, source_root) or _category(module)


def build_evaluate_graph(config: Config):
    def classify(state: EngineState) -> dict:
        gap_report = state.get("audit_gap_report") or {}
        source_root = Path(state["source_root"])
        candidates: list[dict] = []
        for g in gap_report.get("gaps", []):
            if not g.get("is_boundary"):
                continue
            cat, pattern = _classify(g["module"], source_root)
            risk = _RISK[cat]
            tier_weight = 3  # boundary fns are runtime-tier
            gap = max(0.0, (100.0 - float(g.get("coverage_pct", 100.0))) / 100.0)
            candidates.append({
                "module": g["module"],
                "boundary_fn": g["function_name"],
                "tier": "runtime",
                "category": cat,
                "risk": risk,
                "tier_weight": tier_weight,
                "gap": round(gap, 3),
                "score": round(tier_weight * risk * gap, 3),
                "pattern": pattern,
            })
        candidates.sort(key=lambda c: c["score"], reverse=True)
        strategies = [{"module": c["module"], "candidates": [c]} for c in candidates]
        return {
            "integration_strategies": strategies,
            "log": [f"evaluate/classify: {len(candidates)} real-integration "
                    "candidates ranked by replacement value"],
        }

    def gate(state: EngineState) -> dict:
        strategies = state.get("integration_strategies", [])
        decision = human_gate(config, StageName.evaluate, {
            "strategies": len(strategies),
            "top": strategies[0] if strategies else None,
        })
        return {"approvals": {**state.get("approvals", {}), "evaluate": decision},
                "log": [f"evaluate/gate: approve={decision.get('approve')}"]}

    g = StateGraph(EngineState)
    g.add_node("classify", classify)
    g.add_node("gate", gate)
    g.add_edge(START, "classify")
    g.add_edge("classify", "gate")
    g.add_edge("gate", END)
    return g.compile()


__all__ = ["build_evaluate_graph"]
