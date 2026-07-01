"""`integrate` subgraph — turn ranked mock-heavy seams into real-service tests.

Take the ranked IntegrationStrategy candidates from ``evaluate`` and, per item,
ask the LLM to propose a real-service test using the assigned lifecycle pattern
(testcontainers / vcrpy / tmp_path / …), then HARD-GATE. In apply-mode
(``integrate.apply``) each approved proposal is written to disk and checked —
valid Python, no leaked cassette/credential secrets, green when run, and stable
under a flakiness re-run — before it is recorded. Otherwise the stage is
propose-only: proposals are surfaced for the gate and recorded, no files written.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..backends import LLMBackend
from ..config import Config, StageName
from ..knowledge import build_system_prompt
from ..state import EngineState
from ..tools import adapters
from ._gates import human_gate
from ._testrun import flakiness, green_run, test_path, valid_python


def build_integrate_graph(config: Config, backend: LLMBackend | None = None):
    integ = config.integrate

    def plan(state: EngineState) -> dict:
        strategies = state.get("integration_strategies", [])
        return {"log": [f"integrate/plan: {len(strategies)} items queued "
                        "(ordered by replacement value)"]}

    def convert(state: EngineState) -> dict:
        strategies = state.get("integration_strategies", [])
        if not strategies:
            return {"int_pending": [], "log": ["integrate/convert: nothing to integrate"]}
        if backend is None or not config.is_enabled(StageName.integrate):
            return {"int_pending": [],
                    "log": [f"integrate/convert: {len(strategies)} items need real "
                            "tests (skipped — no backend / stage disabled)"]}
        system = build_system_prompt(
            "integrate",
            references=("testcontainers-patterns", "real-api-testing"),
        )
        proposals: list[dict] = []
        errors: list[str] = []
        for s in strategies[: config.loop.max_gaps_per_cycle]:
            # one bad candidate or LLM failure must not abort the whole stage
            try:
                cand = s["candidates"][0]
                code = backend.invoke(
                    f"Propose a real-service integration test for boundary function "
                    f"`{cand['boundary_fn']}` in `{cand['module']}` (category "
                    f"{cand['category']}, lifecycle pattern '{cand['pattern']}'). "
                    "Output only the test code.",
                    system=system,
                )
            except Exception as exc:  # noqa: BLE001
                fn = (s.get("candidates") or [{}])[0].get("boundary_fn", "?")
                errors.append(f"integrate/convert: {fn} failed: {exc}")
                continue
            proposals.append({**cand, "proposed_test": code})
        out: dict = {
            "int_pending": proposals,
            "log": [f"integrate/convert: drafted {len(proposals)} real-service tests"
                    + (f", {len(errors)} failed" if errors else "")],
        }
        if errors:
            out["errors"] = errors
        return out

    def gate(state: EngineState) -> dict:
        pending = state.get("int_pending", [])
        decision = human_gate(config, StageName.integrate, {
            "proposed_tests": len(pending),
            "apply": integ.apply,
        })
        return {"approvals": {**state.get("approvals", {}), "integrate": decision},
                "log": [f"integrate/gate: approve={decision.get('approve')}"]}

    def _finalize(state: EngineState, p: dict) -> tuple[dict, str]:
        root = Path(state["project_root"])
        test_root = Path(state["test_root"])
        module, fn = p["module"], p["boundary_fn"]
        tpath = test_path(test_root, integ.generated_subdir, module, fn)
        tpath.parent.mkdir(parents=True, exist_ok=True)
        code = p["proposed_test"]
        tpath.write_text(code, encoding="utf-8")

        fail_rate: float | None = None
        secrets: list[str] | None = None
        if not valid_python(code):
            status = "syntax-error"
        else:
            scan = adapters.run_secret_scan(tpath)
            if scan.ok and scan.data and scan.data.get("has_secrets"):
                secrets = [f.get("pattern_name", "?") for f in scan.data.get("findings", [])]
                status = "secret-found"  # never keep a test that leaks credentials
            elif green_run(root, tpath)[0] is False:
                status = "red"
            elif (fk := flakiness(root, tpath, config.thresholds))[0]:
                fail_rate = fk[1]
                status = "flaky"
            else:
                fail_rate = fk[1]
                status = "pass"

        rec = {k: v for k, v in p.items() if k != "proposed_test"}
        rec.update({"test_path": str(tpath), "gate": status,
                    "flakiness_fail_rate": fail_rate, "secrets": secrets})
        return rec, f"integrate/apply: {module}.{fn} -> {tpath.name} [{status}]"

    def apply(state: EngineState) -> dict:
        pending = state.get("int_pending", [])
        approved = state.get("approvals", {}).get("integrate", {}).get("approve", False)
        if not pending:
            return {"log": ["integrate/apply: nothing to apply"]}
        if not approved:
            return {"int_pending": [],
                    "log": ["integrate/apply: batch rejected at gate; discarded"]}
        if not integ.apply:
            return {"generated": [*state.get("generated", []), *pending],
                    "int_pending": [],
                    "log": [f"integrate/apply: propose-only, recorded {len(pending)} "
                            "drafts (set integrate.apply=true to write + check)"]}
        finalized, logs = [], []
        for p in pending:
            rec, log = _finalize(state, p)
            finalized.append(rec)
            logs.append(log)
        return {"generated": [*state.get("generated", []), *finalized],
                "int_pending": [], "log": logs}

    g = StateGraph(EngineState)
    g.add_node("plan", plan)
    g.add_node("convert", convert)
    g.add_node("gate", gate)
    g.add_node("apply", apply)
    g.add_edge(START, "plan")
    g.add_edge("plan", "convert")
    g.add_edge("convert", "gate")
    g.add_edge("gate", "apply")
    g.add_edge("apply", END)
    return g.compile()


__all__ = ["build_integrate_graph"]
