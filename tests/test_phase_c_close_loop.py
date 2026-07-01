"""Phase C — close the loop: --apply wiring, integrate apply (write + secret-scan
+ flakiness), and the generate flakiness gate. Hermetic (FakeBackend); the slow
flakiness checker is stubbed stable by the autouse conftest fixture, overridden
where a test needs a flaky verdict."""

from __future__ import annotations

import shutil
from pathlib import Path

from pyverdex.backends import FakeBackend
from pyverdex.cli import _load_config
from pyverdex.config import Config, GateMode, StageConfig, StageName
from pyverdex.graph import build_engine, initial_state
from pyverdex.skills.integrate import build_integrate_graph
from pyverdex.tools import adapters
from pyverdex.tools.adapters import ToolResult

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "examples" / "sample_project"

CAND = {"module": "sample.calc", "boundary_fn": "classify", "tier": "runtime",
        "category": "api", "risk": 4, "gap": 0.25, "score": 3.0, "pattern": "vcrpy"}

REAL_INT_TEST = '''\
"""A real-service style integration test that actually imports + exercises the code."""
from sample.calc import classify


def test_classify_boundary():
    assert classify(-1) == "neg"
    assert classify(3) == "pos"
'''

SECRET_TEST = '''\
from sample.calc import classify

API_KEY = "AKIAIOSFODNN7EXAMPLE"  # a leaked AWS key must fail the gate


def test_classify():
    assert classify(0) == "zero"
'''

STRONG_TEST = '''\
"""Covers the negative and zero branches of classify."""
from sample.calc import classify


def test_classify_negative_and_zero():
    assert classify(-5) == "neg"
    assert classify(0) == "zero"
'''


# --- --apply flag wiring ---------------------------------------------------

def test_apply_flag_closes_both_loops():
    cfg = _load_config(None, str(SAMPLE), None, None, apply=True)
    assert cfg.generate.apply is True
    assert cfg.integrate.apply is True


def test_no_apply_flag_stays_propose_only():
    cfg = _load_config(None, str(SAMPLE), None, None, apply=False)
    assert cfg.generate.apply is False
    assert cfg.integrate.apply is False


# --- integrate apply path --------------------------------------------------

def _integrate_cfg(project: Path, tmp_path: Path, *, apply: bool) -> Config:
    cfg = Config()
    cfg.project_root = str(project)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    cfg.paths.report_dir = str(tmp_path / "report")
    cfg.paths.state_dir = str(tmp_path / "state")
    cfg.integrate.apply = apply
    cfg.stages = {n: StageConfig(enabled=True, gate=GateMode.auto) for n in StageName}
    cfg.ensure_dirs()
    return cfg


def _run_integrate(cfg: Config, backend: FakeBackend) -> dict:
    graph = build_integrate_graph(cfg, backend=backend)
    return graph.invoke({
        "project_root": str(cfg.root), "test_root": str(cfg.abs_test_root),
        "integration_strategies": [{"module": "sample.calc", "candidates": [CAND]}],
        "generated": [], "approvals": {}, "log": [], "errors": [], "int_pending": [],
    })


def test_integrate_apply_writes_and_passes(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = _integrate_cfg(project, tmp_path, apply=True)
    out = _run_integrate(cfg, FakeBackend(lambda _p: REAL_INT_TEST))

    rec = next(r for r in out["generated"] if r.get("boundary_fn") == "classify")
    assert rec["gate"] == "pass"          # written, green, secret-clean, stable
    assert rec["secrets"] is None
    assert Path(rec["test_path"]).exists()  # a real file on disk
    assert (project / "tests" / "pyverdex_integration").exists()


def test_integrate_apply_rejects_leaked_secret(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = _integrate_cfg(project, tmp_path, apply=True)
    out = _run_integrate(cfg, FakeBackend(lambda _p: SECRET_TEST))

    rec = next(r for r in out["generated"] if r.get("boundary_fn") == "classify")
    assert rec["gate"] == "secret-found"
    assert "aws_access_key" in (rec["secrets"] or [])


def test_integrate_propose_only_writes_nothing(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = _integrate_cfg(project, tmp_path, apply=False)
    out = _run_integrate(cfg, FakeBackend(lambda _p: REAL_INT_TEST))

    rec = next(r for r in out["generated"] if r.get("boundary_fn") == "classify")
    assert "proposed_test" in rec       # kept as a proposal
    assert "test_path" not in rec       # nothing written
    assert not (project / "tests" / "pyverdex_integration").exists()


# --- generate flakiness gate -----------------------------------------------

def test_generate_rejects_flaky_test(tmp_path, monkeypatch):
    # override the conftest stub: report the authored test as flaky
    monkeypatch.setattr(adapters, "run_flakiness", lambda *a, **k: ToolResult(
        tool="flakiness-checker", returncode=1,
        data={"total_runs": 10, "failures": 6, "fail_rate": 0.6,
              "status": "flaky-quarantined"}))

    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = Config()
    cfg.project_root = str(project)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    cfg.paths.report_dir = str(tmp_path / "report")
    cfg.paths.state_dir = str(tmp_path / "state")
    cfg.generate.apply = True
    cfg.stages = {n: StageConfig(
        enabled=(n in (StageName.audit, StageName.generate, StageName.report)),
        gate=GateMode.auto) for n in StageName}
    cfg.ensure_dirs()

    eng = build_engine(cfg, backend=FakeBackend(lambda _p: STRONG_TEST))
    state = eng.invoke(initial_state(cfg), {"configurable": {"thread_id": "flaky"}})

    rec = next(r for r in state["generated"] if r.get("function_name") == "classify")
    assert rec["gate"] == "flaky"                 # rejected before mutation
    assert rec["flakiness_fail_rate"] == 0.6
