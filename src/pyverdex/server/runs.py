"""In-memory run manager: executes the engine in a thread, streams its log.

Web runs force every gate to ``auto`` (the browser flow is unattended); use the
CLI / web terminal for the human-gated, interrupt/resume workflow.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import Config, GateMode, StageName, parse_levels
from ..discovery import discover_config, project_info
from ..graph import build_engine, initial_state


@dataclass
class Run:
    id: str
    project_root: str
    status: str = "running"  # running | done | error
    logs: list[str] = field(default_factory=list)
    report: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    info: dict[str, Any] = field(default_factory=dict)

    def snapshot(self, log_offset: int = 0) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_root": self.project_root,
            "status": self.status,
            "logs": self.logs[log_offset:],
            "log_count": len(self.logs),
            "report": self.report,
            "error": self.error,
            "info": self.info,
        }


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def get(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def start(
        self,
        path: str,
        *,
        apply: bool = False,
        provider: Optional[str] = None,
        max_cycles: Optional[int] = None,
        level: Optional[str] = None,
    ) -> Run:
        cfg = discover_config(path)
        # web flow is unattended: all gates auto
        cfg.stages = {n: cfg.stage(n).model_copy(update={"gate": GateMode.auto})
                      for n in StageName}
        if level:
            # restrict to the requested test level(s) (raises ValueError on a bad
            # token — the API layer turns that into a 400)
            cfg.apply_levels(parse_levels(level))
        cfg.generate.apply = apply
        cfg.integrate.apply = apply
        if provider:
            cfg.model.provider = provider
        if max_cycles is not None:
            cfg.loop.max_cycles = max_cycles
        cfg.ensure_dirs()

        run = Run(id=uuid.uuid4().hex[:12], project_root=str(cfg.root),
                  info=project_info(cfg))
        with self._lock:
            self._runs[run.id] = run
        threading.Thread(target=self._execute, args=(run, cfg), daemon=True).start()
        return run

    def _execute(self, run: Run, cfg: Config) -> None:
        try:
            engine = build_engine(cfg)
            seen = 0
            for values in engine.stream(
                initial_state(cfg),
                {"configurable": {"thread_id": f"web-{run.id}"}},
                stream_mode="values",
            ):
                log = values.get("log", [])
                if len(log) > seen:
                    run.logs.extend(log[seen:])
                    seen = len(log)
                for err in values.get("errors", []):
                    if err not in run.logs:
                        run.logs.append(f"! {err}")
                if values.get("unified_coverage"):
                    run.report = values["unified_coverage"]
            run.status = "done"
            run.logs.append(f"run finished: {run.report.get('overall_status') if run.report else 'no report'}")
        except Exception as exc:  # noqa: BLE001 — report to the UI, never crash the server
            run.status = "error"
            run.error = str(exc)
            run.logs.append(f"! run failed: {exc}")


MANAGER = RunManager()

__all__ = ["Run", "RunManager", "MANAGER"]
