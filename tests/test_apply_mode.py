"""Apply-mode (loop-closure) + backend tests — hermetic, FakeBackend only."""

from __future__ import annotations

import shutil
from pathlib import Path

from pyverify.backends import FakeBackend, backend_available
from pyverify.config import Config, GateMode, StageConfig, StageName
from pyverify.graph import build_engine, initial_state

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "examples" / "sample_project"

STRONG_TEST = '''\
"""Covers the negative and zero branches of classify."""
from sample.calc import classify


def test_classify_negative_and_zero():
    assert classify(-5) == "neg"
    assert classify(0) == "zero"
'''


def _apply_cfg(project: Path, tmp_path: Path) -> Config:
    cfg = Config()
    cfg.project_root = str(project)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    cfg.paths.report_dir = str(tmp_path / "report")
    cfg.paths.state_dir = str(tmp_path / "state")
    cfg.generate.apply = True
    cfg.stages = {
        n: StageConfig(enabled=(n in (StageName.audit, StageName.generate, StageName.report)),
                       gate=GateMode.auto)
        for n in StageName
    }
    cfg.ensure_dirs()
    return cfg


def test_apply_mode_closes_the_loop(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = _apply_cfg(project, tmp_path)
    fake = FakeBackend(lambda _prompt: STRONG_TEST)

    eng = build_engine(cfg, backend=fake)
    state = eng.invoke(initial_state(cfg), {"configurable": {"thread_id": "apply-test"}})

    # the test was authored, written, and mutation-gated
    gen = state["generated"]
    assert len(gen) == 1
    rec = gen[0]
    assert rec["function_name"] == "classify"
    assert rec["gate"] == "pass"
    assert rec["mutation_kill_rate"] == 1.0
    assert Path(rec["test_path"]).exists()

    # the loop re-audited and coverage targets are now met
    assert state["coverage_met"] is True
    assert "sample.calc::classify" in state["gen_handled"]
    assert fake.calls == 1  # authored once, no restrengthen needed


def test_propose_only_writes_nothing(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = _apply_cfg(project, tmp_path)
    cfg.generate.apply = False  # propose-only
    fake = FakeBackend(lambda _prompt: STRONG_TEST)

    eng = build_engine(cfg, backend=fake)
    state = eng.invoke(initial_state(cfg), {"configurable": {"thread_id": "propose-test"}})

    assert len(state["generated"]) == 1
    assert "test_path" not in state["generated"][0]  # nothing written
    assert not (project / "tests" / "pyverify_generated").exists()
    assert state["loop_exhausted"] is True


def test_fake_backend_available_and_records():
    fake = FakeBackend(lambda p: f"echo:{p}")
    assert fake.invoke("hi", system="s") == "echo:hi"
    assert fake.prompts == ["hi"]
    assert fake.calls == 1


def test_backend_availability_flags():
    anthropic_cfg = Config()
    anthropic_cfg.model.provider = "anthropic"
    # availability depends only on env var presence; just assert it returns a bool
    assert isinstance(backend_available(anthropic_cfg), bool)
