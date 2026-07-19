"""Phase G — plumbing/contract locks for system (boundary) coverage + log-path.

The unit tests in test_report_builder.py exercise the pure join over synthetic
state. These two tests lock the plumbing that join assumes:

- gap #1: the audit graph actually POPULATES the two state keys the builder
  reads — ``boundary_report`` (the denominator) and ``log_contract_report``
  (the previously-dropped log-path dimension).
- gap #2: a REAL integrate-apply record joins to a boundary end-to-end through
  ``build_unified_report`` — locking the field-name contract between integrate
  (``boundary_fn`` / ``test_path`` / ``gate``) and the builder's matcher. If
  integrate renamed ``boundary_fn``, the boundary would silently read uncovered
  and this test fails.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pyverdex.backends import FakeBackend
from pyverdex.config import Config, GateMode, StageConfig, StageName
from pyverdex.models import DimensionStatus
from pyverdex.report.builder import build_unified_report
from pyverdex.skills.audit import build_audit_graph
from pyverdex.skills.integrate import build_integrate_graph

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "examples" / "sample_project"


# --- gap #1: audit really produces boundary_report + log_contract_report ----

def _boundary_project(tmp_path: Path) -> Path:
    """A runnable project with a real env_reader boundary and a logged branch."""
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
    pkg = tmp_path / "src" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "api.py").write_text(
        "import os\n"
        "import logging\n\n"
        "log = logging.getLogger(__name__)\n\n"
        "def handler(flag):\n"
        "    if flag:\n"
        "        log.info('on')\n"                       # a logged branch (log-path)
        "    return os.environ.get('KEY', 'x')\n",        # os.environ -> env_reader boundary
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_api.py").write_text(
        "from svc.api import handler\n\ndef test_handler():\n    assert handler(1) is not None\n",
        encoding="utf-8",
    )
    return tmp_path


def _audit_cfg(project: Path) -> Config:
    cfg = Config()
    cfg.project_root = str(project)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    return cfg


def _audit_state(cfg: Config) -> dict:
    return {"project_root": str(cfg.root), "source_root": str(cfg.abs_source_root),
            "test_root": str(cfg.abs_test_root), "log": [], "errors": []}


def test_audit_populates_boundary_and_log_reports(tmp_path):
    cfg = _audit_cfg(_boundary_project(tmp_path))
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))

    # boundary_report: the builder's system-coverage DENOMINATOR source
    assert "boundary_report" in out
    pairs = {(b["module"], b["function_name"]) for b in out["boundary_report"]["boundaries"]}
    assert ("svc.api", "handler") in pairs  # os.environ read => env_reader boundary

    # log_contract_report: source for the previously-dropped log-path dimension
    assert "log_contract_report" in out
    assert "total_branches" in out["log_contract_report"]


def test_audit_boundary_report_flows_into_report_dimension(tmp_path):
    """The audit-produced boundary_report yields a system dimension in the built
    report. Since Phase H the numerator counts ALL tests via per-test coverage
    contexts: the fixture's hand-written asserting test covers the boundary, so
    this locks the full audit→attribution→builder flow (not just the engine
    join). The engine-only fallback keeps Phase G semantics and is locked in
    test_phase_h_contexts.py."""
    cfg = _audit_cfg(_boundary_project(tmp_path))
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    report = build_unified_report({**_audit_state(cfg), **out, "generated": []}, cfg)
    assert report.boundaries_total >= 1
    # test_handler executes handler() and asserts on its result -> covered;
    # it replaces no dependency, so realness (Phase H2) grades it real_covered
    assert report.boundaries_covered == report.boundaries_total
    assert report.boundaries_real_covered == report.boundaries_total
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.status is DimensionStatus.passed
    assert dim.detail["attribution"] == "contexts+realness"
    assert dim.detail["engine_covered"] == 0  # no integration tests written
    assert dim.detail["untested_sample"] == []


# --- gap #2: a REAL integrate record marks its boundary covered --------------

CAND = {"module": "sample.calc", "boundary_fn": "classify", "tier": "runtime",
        "category": "api", "risk": 4, "gap": 0.25, "score": 3.0, "pattern": "vcrpy"}

REAL_INT_TEST = '''\
from sample.calc import classify


def test_classify_boundary():
    assert classify(-1) == "neg"
    assert classify(3) == "pos"
'''


def _integrate_cfg(project: Path, tmp_path: Path) -> Config:
    cfg = Config()
    cfg.project_root = str(project)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    cfg.paths.report_dir = str(tmp_path / "report")
    cfg.paths.state_dir = str(tmp_path / "state")
    cfg.integrate.apply = True
    cfg.stages = {n: StageConfig(enabled=True, gate=GateMode.auto) for n in StageName}
    cfg.ensure_dirs()
    return cfg


def test_real_integrate_record_marks_boundary_covered(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = _integrate_cfg(project, tmp_path)

    # real integrate apply: writes the test, green-runs + secret-scans it (flakiness
    # is the autouse-stubbed stable checker), producing a real passing record.
    out = build_integrate_graph(cfg, backend=FakeBackend(lambda _p: REAL_INT_TEST)).invoke({
        "project_root": str(cfg.root), "test_root": str(cfg.abs_test_root),
        "integration_strategies": [{"module": "sample.calc", "candidates": [CAND]}],
        "generated": [], "approvals": {}, "log": [], "errors": [], "int_pending": [],
    })
    rec = next(r for r in out["generated"] if r.get("boundary_fn") == "classify")
    assert rec["gate"] == "pass"  # a real green-run produced a passing record

    # feed the REAL record + a boundary_report naming that boundary into the builder
    state = {
        "project_root": str(cfg.root), "source_root": str(cfg.abs_source_root),
        "test_root": str(cfg.abs_test_root),
        "boundary_report": {"boundaries": [
            {"module": "sample.calc", "function_name": "classify",
             "boundary_type": "exported_public"}]},
        "generated": out["generated"],
    }
    report = build_unified_report(state, cfg)
    # the contract holds: integrate's boundary_fn/test_path/gate joined on (module, fn)
    assert report.boundaries_total == 1
    assert report.boundaries_covered == 1
    assert report.boundary_coverage_pct == 100.0
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.status is DimensionStatus.passed


def test_real_integrate_failing_record_does_not_cover_boundary(tmp_path, monkeypatch):
    """A written-but-FAILING integration record must NOT count as covered — the
    numerator requires gate=='pass', not merely that a test was written."""
    from pyverdex.tools import adapters
    from pyverdex.tools.adapters import ToolResult
    # force the flakiness checker to reject the written test (gate => flaky)
    monkeypatch.setattr(adapters, "run_flakiness", lambda *a, **k: ToolResult(
        tool="flakiness-checker", returncode=1,
        data={"total_runs": 10, "failures": 7, "fail_rate": 0.7, "status": "flaky"}))
    project = tmp_path / "proj"
    shutil.copytree(SAMPLE, project)
    cfg = _integrate_cfg(project, tmp_path)
    out = build_integrate_graph(cfg, backend=FakeBackend(lambda _p: REAL_INT_TEST)).invoke({
        "project_root": str(cfg.root), "test_root": str(cfg.abs_test_root),
        "integration_strategies": [{"module": "sample.calc", "candidates": [CAND]}],
        "generated": [], "approvals": {}, "log": [], "errors": [], "int_pending": [],
    })
    rec = next(r for r in out["generated"] if r.get("boundary_fn") == "classify")
    assert rec["gate"] != "pass"  # rejected

    state = {
        "project_root": str(cfg.root), "source_root": str(cfg.abs_source_root),
        "test_root": str(cfg.abs_test_root),
        "boundary_report": {"boundaries": [
            {"module": "sample.calc", "function_name": "classify",
             "boundary_type": "exported_public"}]},
        "generated": out["generated"],
    }
    report = build_unified_report(state, cfg)
    assert report.boundaries_total == 1
    assert report.boundaries_covered == 0  # written but not passing => not covered
    assert report.boundary_coverage_pct == 0.0
