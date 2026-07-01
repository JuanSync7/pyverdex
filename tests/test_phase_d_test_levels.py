"""Phase D — test-level taxonomy: the TestLevel enum, --level → stage selection,
per-stage level tagging (generate=unit, integrate=integration), and the audit
import-smoke sweep. Hermetic (FakeBackend; flakiness stubbed by conftest)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from pyverdex.backends import FakeBackend
from pyverdex.cli import _load_config
from pyverdex.config import Config, GateMode, StageConfig, StageName, parse_levels
from pyverdex.models import TestLevel
from pyverdex.skills.audit import build_audit_graph
from pyverdex.skills.generate import build_generate_graph
from pyverdex.skills.integrate import build_integrate_graph
from pyverdex.tools import adapters

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "examples" / "sample_project"

UNIT_TEST = '''\
"""A real unit test for classify."""
from sample.calc import classify


def test_classify_units():
    assert classify(-2) == "neg"
    assert classify(0) == "zero"
'''

INT_CAND = {"module": "sample.calc", "boundary_fn": "classify", "tier": "runtime",
            "category": "api", "risk": 4, "gap": 0.25, "score": 3.0, "pattern": "vcrpy"}


# --- TestLevel enum + parse_levels -----------------------------------------

def test_testlevel_values_are_strings():
    assert [lvl.value for lvl in TestLevel] == ["smoke", "unit", "integration", "e2e"]
    assert TestLevel.unit == "unit"  # str-Enum: compares/serializes as its value


def test_parse_levels_single_comma_and_dedup():
    assert parse_levels("unit") == [TestLevel.unit]
    assert parse_levels("smoke, unit ,UNIT") == [TestLevel.smoke, TestLevel.unit]


def test_parse_levels_rejects_unknown():
    with pytest.raises(ValueError, match="unknown test level 'bogus'"):
        parse_levels("bogus")
    with pytest.raises(ValueError, match="no test level given"):
        parse_levels("  , ")


# --- Config.apply_levels → stage selection ---------------------------------

def _enabled(cfg: Config) -> set[str]:
    return {n.value for n in StageName if cfg.is_enabled(n)}


def _leveled(*levels: TestLevel) -> set[str]:
    cfg = Config()
    cfg.apply_levels(list(levels))
    return _enabled(cfg)


def test_apply_levels_selects_expected_stages():
    assert _leveled(TestLevel.smoke) == {"audit", "report"}
    assert _leveled(TestLevel.unit) == {"audit", "generate", "report"}
    assert _leveled(TestLevel.integration) == {"audit", "evaluate", "integrate", "report"}
    # e2e is reserved: currently aliases the integration pipeline (ADR 0002)
    assert _leveled(TestLevel.e2e) == _leveled(TestLevel.integration)


def test_apply_levels_unions_and_preserves_gate():
    cfg = Config()
    cfg.apply_levels([TestLevel.unit, TestLevel.integration])
    assert _enabled(cfg) == {"audit", "evaluate", "generate", "integrate", "report"}
    # gate modes are untouched — generate stays gated by default
    assert cfg.stage(StageName.generate).gate is GateMode.gated


# --- --level threading through the CLI loader ------------------------------

def test_load_config_level_narrows_stages():
    cfg = _load_config(None, str(SAMPLE), None, None, level="smoke")
    assert _enabled(cfg) == {"audit", "report"}


def test_load_config_bad_level_raises_bad_parameter():
    with pytest.raises(typer.BadParameter):
        _load_config(None, str(SAMPLE), None, None, level="nope")


def test_load_config_no_level_runs_all_stages():
    cfg = _load_config(None, str(SAMPLE), None, None)
    assert cfg.is_enabled(StageName.lint) and cfg.is_enabled(StageName.integrate)


# --- import-smoke sweep -----------------------------------------------------

def test_import_smoke_clean_project():
    res = adapters.run_import_smoke(SAMPLE / "src", SAMPLE)
    assert res.ok and res.data is not None
    assert res.data["total"] == res.data["imported"]  # sample imports cleanly
    assert res.data["failures"] == []


def test_import_smoke_reports_broken_module(tmp_path):
    src = tmp_path / "src" / "brokenpkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "good.py").write_text("VALUE = 1\n")
    (src / "bad.py").write_text("import a_module_that_does_not_exist_zzz\n")
    res = adapters.run_import_smoke(tmp_path / "src", tmp_path)
    assert res.ok and res.data is not None
    assert res.data["total"] == 3 and res.data["imported"] == 2
    failed = {f["module"] for f in res.data["failures"]}
    assert failed == {"brokenpkg.bad"}


def test_import_smoke_honours_excludes(tmp_path):
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "bad.py").write_text("import nonexistent_zzz\n")
    # excluding the file's own package drops it from the sweep entirely
    res = adapters.run_import_smoke(tmp_path / "src", tmp_path, exclude=["pkg"])
    assert res.data["total"] == 0 and res.data["failures"] == []


def test_import_smoke_records_systemexit_at_import(tmp_path):
    # a module that sys.exit()s at import must be recorded as a failure, NOT crash
    # the whole sweep (SystemExit is a BaseException, not an Exception)
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "good.py").write_text("OK = 1\n")
    (src / "boom.py").write_text("import sys\nsys.exit(3)\n")
    res = adapters.run_import_smoke(tmp_path / "src", tmp_path)
    assert res.ok and res.data is not None  # sweep still produced a report
    assert res.data["imported"] == 2  # pkg + pkg.good
    assert {f["module"] for f in res.data["failures"]} == {"pkg.boom"}


def test_import_smoke_covers_namespace_packages(tmp_path):
    # PEP 420 namespace package (no __init__.py) must still be swept
    src = tmp_path / "src" / "nspkg"
    src.mkdir(parents=True)
    (src / "mod.py").write_text("VALUE = 1\n")
    res = adapters.run_import_smoke(tmp_path / "src", tmp_path)
    assert res.data["total"] == 1 and res.data["imported"] == 1
    # a non-identifier dir/file name is skipped (not a valid dotted module)
    (tmp_path / "src" / "data-dir").mkdir()
    (tmp_path / "src" / "data-dir" / "x.py").write_text("Y = 2\n")
    res2 = adapters.run_import_smoke(tmp_path / "src", tmp_path)
    assert res2.data["total"] == 1  # data-dir.* is not importable, so skipped


# --- audit wires the smoke sweep into state --------------------------------

def _audit_state(cfg: Config) -> dict:
    return {"project_root": str(cfg.root), "source_root": str(cfg.abs_source_root),
            "test_root": str(cfg.abs_test_root), "log": [], "errors": []}


def _sample_cfg() -> Config:
    cfg = Config()
    cfg.project_root = str(SAMPLE)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    return cfg


def test_audit_populates_smoke_report():
    out = build_audit_graph(_sample_cfg()).invoke(_audit_state(_sample_cfg()))
    assert "smoke_report" in out
    assert out["smoke_report"]["imported"] == out["smoke_report"]["total"] > 0


def test_audit_import_smoke_toggle_off():
    cfg = _sample_cfg()
    cfg.audit.import_smoke = False
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    assert "smoke_report" not in out


# --- per-stage level tagging (propose-only, no files written) --------------

def _propose_cfg(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.project_root = str(SAMPLE)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    cfg.paths.report_dir = str(tmp_path / "report")
    cfg.paths.state_dir = str(tmp_path / "state")
    cfg.stages = {n: StageConfig(enabled=True, gate=GateMode.auto) for n in StageName}
    cfg.ensure_dirs()
    return cfg


def test_generate_tags_records_unit(tmp_path):
    cfg = _propose_cfg(tmp_path)  # generate.apply stays False => propose-only
    graph = build_generate_graph(cfg, backend=FakeBackend(lambda _p: UNIT_TEST))
    out = graph.invoke({
        "project_root": str(cfg.root), "source_root": str(cfg.abs_source_root),
        "test_root": str(cfg.abs_test_root),
        "audit_gap_report": {"gaps": [{
            "module": "sample.calc", "function_name": "classify",
            "line_start": 1, "line_end": 9, "coverage_pct": 50.0,
            "missing_lines": [3], "tier": "standard",
            "reason": "line 50% < 85% (standard)"}]},
        "gen_handled": [], "gen_pending": [], "generated": [], "approvals": {},
        "cycle": 0, "log": [], "errors": [],
    })
    rec = next(r for r in out["generated"] if r.get("function_name") == "classify")
    assert rec["test_level"] == TestLevel.unit.value
    assert "test_path" not in rec  # propose-only: nothing written


def test_integrate_tags_records_integration(tmp_path):
    cfg = _propose_cfg(tmp_path)  # integrate.apply stays False => propose-only
    graph = build_integrate_graph(cfg, backend=FakeBackend(lambda _p: "x = 1\n"))
    out = graph.invoke({
        "project_root": str(cfg.root), "test_root": str(cfg.abs_test_root),
        "integration_strategies": [{"module": "sample.calc", "candidates": [INT_CAND]}],
        "generated": [], "approvals": {}, "int_pending": [], "log": [], "errors": [],
    })
    rec = next(r for r in out["generated"] if r.get("boundary_fn") == "classify")
    assert rec["test_level"] == TestLevel.integration.value
    assert "test_path" not in rec  # propose-only
