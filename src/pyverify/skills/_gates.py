"""Human-in-the-loop gate helper.

A gate is a LangGraph ``interrupt()`` that fires only when the stage's
configured :class:`~pyverify.config.GateMode` is ``gated``. When ``auto``,
the gate is transparent. On resume, the orchestrator passes a decision via
``Command(resume=<decision>)``; ``{"approve": true}`` proceeds.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from ..config import Config, StageName


def human_gate(config: Config, stage: StageName, payload: dict[str, Any]) -> dict[str, Any]:
    """Return the human decision dict. Blocks via interrupt() when gated."""
    if not config.is_gated(stage):
        return {"approve": True, "auto": True, "stage": stage.value}
    decision = interrupt({"stage": stage.value, "gate": payload})
    if isinstance(decision, dict):
        return decision
    if isinstance(decision, bool):
        return {"approve": decision}
    return {"approve": bool(decision)}


__all__ = ["human_gate"]
