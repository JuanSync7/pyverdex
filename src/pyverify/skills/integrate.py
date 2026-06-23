"""`integrate` subgraph — convert mocks to real-service tests (gated, terminal).

Mirrors test-integrate: take the ranked IntegrationStrategy candidates and,
per item, propose a real-service test using the assigned lifecycle pattern
(testcontainers / vcrpy / tmp_path / …), then HARD-GATE before anything is
applied. This build is propose-only: it emits per-item proposals for approval;
flakiness + cassette-secret checks run once tests are actually written.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..backends import LLMBackend
from ..config import Config, StageName
from ..knowledge import build_system_prompt
from ..state import EngineState
from ._gates import human_gate


def build_integrate_graph(config: Config, backend: LLMBackend | None = None):
    def plan(state: EngineState) -> dict:
        strategies = state.get("integration_strategies", [])
        return {"log": [f"integrate/plan: {len(strategies)} items queued "
                        "(ordered by replacement value)"]}

    def convert(state: EngineState) -> dict:
        strategies = state.get("integration_strategies", [])
        if not strategies:
            return {"log": ["integrate/convert: nothing to integrate"]}
        if backend is None or not config.is_enabled(StageName.integrate):
            return {"log": [f"integrate/convert: {len(strategies)} items need real "
                            "tests (skipped — no backend / stage disabled)"]}
        system = build_system_prompt(
            "integrate",
            references=("testcontainers-patterns", "real-api-testing"),
        )
        proposals: list[dict] = []
        for s in strategies[: config.loop.max_gaps_per_cycle]:
            cand = s["candidates"][0]
            code = backend.invoke(
                f"Propose a real-service integration test for boundary function "
                f"`{cand['boundary_fn']}` in `{cand['module']}` (category "
                f"{cand['category']}, lifecycle pattern '{cand['pattern']}'). "
                "Output only the test code.",
                system=system,
            )
            proposals.append({**cand, "proposed_test": code})
        merged = [*state.get("generated", []), *proposals]
        return {"generated": merged,
                "log": [f"integrate/convert: proposed {len(proposals)} real-service tests"]}

    def gate(state: EngineState) -> dict:
        strategies = state.get("integration_strategies", [])
        decision = human_gate(config, StageName.integrate, {
            "items": len(strategies),
        })
        return {"approvals": {**state.get("approvals", {}), "integrate": decision},
                "log": [f"integrate/gate: approve={decision.get('approve')}"]}

    g = StateGraph(EngineState)
    g.add_node("plan", plan)
    g.add_node("convert", convert)
    g.add_node("gate", gate)
    g.add_edge(START, "plan")
    g.add_edge("plan", "convert")
    g.add_edge("convert", "gate")
    g.add_edge("gate", END)
    return g.compile()


__all__ = ["build_integrate_graph"]
