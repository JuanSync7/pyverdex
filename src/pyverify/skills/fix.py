"""`fix` subgraph — remediate lint findings (deterministic + optional LLM).

Mirrors test-fix: the deterministic, always-safe part is ``ruff --fix``
(re-verified by re-running the linter). Anything ruff can't auto-fix
(mypy/bandit/vulture) is summarised; when an LLM is configured it produces a
remediation *plan* (never an unreviewed auto-edit). A gate guards the stage.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..backends import LLMBackend
from ..config import Config, StageName
from ..knowledge import build_system_prompt
from ..state import EngineState
from ..tools import adapters
from ._gates import human_gate


def build_fix_graph(config: Config, backend: LLMBackend | None = None):
    def ruff_fix(state: EngineState) -> dict:
        source = Path(state["source_root"])
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--fix", str(source)],
            capture_output=True, text=True, cwd=state["project_root"],
        )
        after = adapters.run_lint(source)
        remaining = (after.data or {}).get("total_issues", 0) if after.ok else None
        return {
            "fix_report": {"ruff_fix_rc": proc.returncode, "remaining_issues": remaining},
            "lint_report": after.data if after.ok else state.get("lint_report"),
            "log": [f"fix: ruff --fix applied (rc={proc.returncode}); "
                    f"remaining issues={remaining}"],
        }

    def llm_plan(state: EngineState) -> dict:
        report = state.get("lint_report") or {}
        non_ruff = [i for i in report.get("issues", []) if i.get("tool") != "ruff"]
        if not non_ruff:
            return {"log": ["fix: no non-ruff findings to plan"]}
        if backend is None or not config.is_enabled(StageName.fix):
            return {"log": [f"fix: {len(non_ruff)} non-ruff findings need review "
                            "(LLM remediation skipped — no backend / stage disabled)"]}
        system = build_system_prompt("fix")
        sample = non_ruff[:40]
        plan = backend.invoke(
            "Produce a concise, file-by-file remediation plan for these lint "
            "findings. Do not output code patches, only the plan:\n"
            + "\n".join(f"- {i.get('tool')} {i.get('rule_id')} {i.get('file_path')}:"
                        f"{i.get('line')} {i.get('message')}" for i in sample),
            system=system,
        )
        fr = dict(state.get("fix_report") or {})
        fr["remediation_plan"] = plan
        return {"fix_report": fr, "log": [f"fix: LLM remediation plan for "
                                          f"{len(non_ruff)} findings"]}

    def gate(state: EngineState) -> dict:
        decision = human_gate(config, StageName.fix, {
            "fix_report": state.get("fix_report"),
        })
        return {"approvals": {**state.get("approvals", {}), "fix": decision},
                "log": [f"fix: gate decision approve={decision.get('approve')}"]}

    g = StateGraph(EngineState)
    g.add_node("ruff_fix", ruff_fix)
    g.add_node("llm_plan", llm_plan)
    g.add_node("gate", gate)
    g.add_edge(START, "ruff_fix")
    g.add_edge("ruff_fix", "llm_plan")
    g.add_edge("llm_plan", "gate")
    g.add_edge("gate", END)
    return g.compile()


__all__ = ["build_fix_graph"]
