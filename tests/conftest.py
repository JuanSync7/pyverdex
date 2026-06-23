from __future__ import annotations

from pathlib import Path

import pytest

from pyverify.config import Config, GateMode, StageConfig, StageName

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "examples" / "sample_project"


def _stages(enabled: set[StageName], gated: set[StageName]) -> dict:
    return {
        n: StageConfig(enabled=(n in enabled),
                       gate=GateMode.gated if n in gated else GateMode.auto)
        for n in StageName
    }


@pytest.fixture
def sample_root() -> Path:
    return SAMPLE


@pytest.fixture
def deterministic_cfg(tmp_path) -> Config:
    """lint + audit + report only, all gates auto (no LLM, no interrupts)."""
    cfg = Config()
    cfg.project_root = str(SAMPLE)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    cfg.paths.report_dir = str(tmp_path / "report")
    cfg.paths.state_dir = str(tmp_path / "state")
    cfg.paths.checkpoint_db = str(tmp_path / "state" / "ck.sqlite")
    cfg.stages = _stages(
        enabled={StageName.lint, StageName.audit, StageName.report},
        gated=set(),
    )
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def gated_eval_cfg(tmp_path) -> Config:
    """audit + (gated) evaluate + report — exercises the HITL interrupt."""
    cfg = Config()
    cfg.project_root = str(SAMPLE)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    cfg.paths.report_dir = str(tmp_path / "report")
    cfg.paths.state_dir = str(tmp_path / "state")
    cfg.paths.checkpoint_db = str(tmp_path / "state" / "ck.sqlite")
    cfg.stages = _stages(
        enabled={StageName.audit, StageName.evaluate, StageName.report},
        gated={StageName.evaluate},
    )
    cfg.ensure_dirs()
    return cfg
