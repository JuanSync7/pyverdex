"""Phase H1 — per-test dynamic contexts: collection, attribution, verdicts.

Three layers are locked here:

- **rcfile merge (adapters)**: ``coverage run --rcfile`` REPLACES config
  discovery (spike-verified: a naive rcfile silently drops the target's
  ``omit``), so enabling contexts must additively carry the target's own
  ``[run]`` options — and always win on ``dynamic_context``.
- **_contexts reader/join**: real end-to-end runs pin the context-label format
  (test module import name + function; parametrized variants collapse; the
  import-time ``""`` context is excluded), the except-handler attribution that
  Phase I builds on, and the graceful ``None`` degrade.
- **builder verdicts**: ``covered`` vs ``executed_only`` vs ``uncovered`` with
  the assertion-quality join; the engine-only fallback preserves Phase G
  behaviour bit-for-bit when no contexts exist.
"""

from __future__ import annotations

from pathlib import Path

from pyverdex.config import Config
from pyverdex.models import DimensionStatus
from pyverdex.report.builder import build_unified_report
from pyverdex.skills import _contexts
from pyverdex.skills.audit import build_audit_graph
from pyverdex.tools import adapters
from pyverdex.tools.adapters import _contexts_rcfile, _target_run_options


# --- fixture: the spike project (known line numbers matter below) -----------

API_SRC = """\
def fetch(dep):
    try:
        value = dep()
        return {"ok": True, "value": value}
    except RuntimeError:
        return {"ok": False, "value": None}


def double(x):
    return x * 2
"""

TEST_SRC = """\
import pytest
from unittest import mock
from svc.api import fetch, double


def test_ok():
    assert fetch(lambda: 5) == {"ok": True, "value": 5}


def test_failure_path():
    dep = mock.Mock(side_effect=RuntimeError("boom"))
    assert fetch(dep) == {"ok": False, "value": None}


@pytest.mark.parametrize("n", [1, 2])
def test_double(n):
    assert double(n) == n * 2
"""

HAPPY_RETURN_LINE = 4   # only test_ok reaches it
HANDLER_RETURN_LINE = 6  # only test_failure_path forces it
DOUBLE_BODY_LINE = 10


def _ctx_project(tmp_path: Path) -> Path:
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\npythonpath = src\n", encoding="utf-8")
    pkg = tmp_path / "src" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "api.py").write_text(API_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_api.py").write_text(TEST_SRC, encoding="utf-8")
    return tmp_path


def _collect(root: Path, dynamic_contexts: bool) -> None:
    res = adapters.collect_coverage(
        root, root / "src", root / "tests", dynamic_contexts=dynamic_contexts)
    assert res.returncode in (0, 1), res.stderr[-500:]


# --- rcfile merge -----------------------------------------------------------

def test_target_run_options_precedence_and_toml_conversion(tmp_path):
    # no config at all -> no inherited options
    assert _target_run_options(tmp_path) == {}

    # pyproject-only target: toml types normalise to ini strings
    (tmp_path / "pyproject.toml").write_text(
        "[tool.coverage.run]\n"
        'omit = ["*/skip.py", "*/gen/*"]\n'
        "relative_files = true\n",
        encoding="utf-8",
    )
    opts = _target_run_options(tmp_path)
    assert opts["relative_files"] == "true"
    assert "*/skip.py" in opts["omit"] and "*/gen/*" in opts["omit"]

    # .coveragerc outranks pyproject (coverage.py precedence, first file wins)
    (tmp_path / ".coveragerc").write_text(
        "[run]\nomit = */rc_wins.py\n", encoding="utf-8")
    assert _target_run_options(tmp_path) == {"omit": "*/rc_wins.py"}


def test_target_run_options_survives_percent_and_report_only_sections(tmp_path):
    # a literal % in a pattern must not trip configparser interpolation
    (tmp_path / ".coveragerc").write_text(
        "[run]\nomit = */%templates/*.py\n", encoding="utf-8")
    assert _target_run_options(tmp_path) == {"omit": "*/%templates/*.py"}
    (tmp_path / ".coveragerc").unlink()

    # setup.cfg with only [coverage:report] still claims the config slot
    # (coverage.py uses the first file WITH coverage sections) -> empty [run],
    # pyproject is NOT consulted
    (tmp_path / "setup.cfg").write_text(
        "[coverage:report]\nshow_missing = True\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.coverage.run]\nomit = ["*/never.py"]\n', encoding="utf-8")
    assert _target_run_options(tmp_path) == {}


def test_contexts_rcfile_merges_target_options_and_wins_on_dynamic_context(tmp_path):
    (tmp_path / ".coveragerc").write_text(
        "[run]\nconcurrency = thread\ndynamic_context = none\n", encoding="utf-8")
    rcfile = _contexts_rcfile(tmp_path)
    try:
        # absolute: the runner unlinks it in a finally, and a relative path
        # would silently miss (and leak) if a test chdir'd meanwhile
        assert rcfile.is_absolute()
        import configparser

        cp = configparser.ConfigParser()
        cp.read(rcfile, encoding="utf-8")
        # target's collection-affecting key preserved; our dynamic_context wins
        assert cp.get("run", "concurrency") == "thread"
        assert cp.get("run", "dynamic_context") == "test_function"
    finally:
        rcfile.unlink()


# --- end-to-end collection + reader (the Step 0 spike, as a regression) -----

def test_collect_with_contexts_records_per_test_labels(tmp_path):
    root = _ctx_project(tmp_path)
    _collect(root, dynamic_contexts=True)

    ctx = _contexts.read_test_contexts(root, root / "src")
    assert ctx is not None and "svc.api" in ctx
    api = ctx["svc.api"]
    # label = test module import name + function (bare tests dir -> no prefix);
    # parametrized variants collapse into ONE label (spike-pinned)
    assert api[DOUBLE_BODY_LINE] == {"test_api.test_double"}
    # the temp rcfile is cleaned up after the run
    assert not list(root.glob(".pyverdex-covrc-*"))


def test_except_handler_attributed_only_to_forcing_test(tmp_path):
    """The failure-path signal Phase I builds on: handler lines belong to the
    test that forced the exception, happy-path lines to the happy test."""
    root = _ctx_project(tmp_path)
    _collect(root, dynamic_contexts=True)
    api = _contexts.read_test_contexts(root, root / "src")["svc.api"]
    assert api[HANDLER_RETURN_LINE] == {"test_api.test_failure_path"}
    assert api[HAPPY_RETURN_LINE] == {"test_api.test_ok"}


def test_merge_preserves_target_omit_end_to_end(tmp_path):
    """A target's own [run] omit must survive contexts injection — a naive
    --rcfile drops it (spike-verified) and would silently measure omitted files."""
    root = _ctx_project(tmp_path)
    (root / "src" / "svc" / "extra.py").write_text("SKIPPED = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[tool.coverage.run]\nomit = ["*/extra.py"]\n', encoding="utf-8")
    _collect(root, dynamic_contexts=True)
    ctx = _contexts.read_test_contexts(root, root / "src")
    assert ctx is not None and "svc.api" in ctx
    assert "svc.extra" not in ctx  # omit honored through the merged rcfile


def test_read_test_contexts_degrades_to_none(tmp_path):
    root = _ctx_project(tmp_path)
    # no .coverage at all
    assert _contexts.read_test_contexts(root, root / "src") is None
    # a real but CONTEXT-FREE DB (toggle off / old run) is "no attribution",
    # never fake zeros
    _collect(root, dynamic_contexts=False)
    assert (root / ".coverage").exists()
    assert _contexts.read_test_contexts(root, root / "src") is None


# --- span computation + pure join -------------------------------------------

def test_function_spans_cover_methods_and_keep_duplicate_names_separate(tmp_path):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "m.py").write_text(
        "def top():\n    return 1\n\n\n"
        "class A:\n    def go(self):\n        return 2\n\n\n"
        "class B:\n    def go(self):\n        return 3\n\n\n"
        "async def later():\n    return 4\n",
        encoding="utf-8",
    )
    spans = _contexts.function_spans(src)
    assert spans[("pkg.m", "top")] == [(1, 2)]
    assert spans[("pkg.m", "later")] == [(15, 16)]
    # same-named methods keep BOTH spans (no merged interval swallowing B's gap)
    assert len(spans[("pkg.m", "go")]) == 2


def test_boundary_test_attribution_joins_spans_with_contexts():
    boundaries = [{"module": "m", "function_name": "f"},
                  {"module": "m", "function_name": "g"},
                  {"module": "other", "function_name": "h"}]
    contexts = {"m": {2: {"test_x.test_a"}, 3: {"test_x.test_b"}, 20: {"test_x.test_c"}}}
    spans = {("m", "f"): [(1, 5)], ("m", "g"): [(10, 12)]}
    attrib = _contexts.boundary_test_attribution(boundaries, contexts, spans)
    assert attrib[("m", "f")] == ["test_x.test_a", "test_x.test_b"]
    assert attrib[("m", "g")] == []      # its span saw no test lines
    assert attrib[("other", "h")] == []  # no span known -> never invented


# --- audit-graph integration -------------------------------------------------

def _audit_cfg(project: Path) -> Config:
    cfg = Config()
    cfg.project_root = str(project)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    return cfg


def _audit_state(cfg: Config) -> dict:
    return {"project_root": str(cfg.root), "source_root": str(cfg.abs_source_root),
            "test_root": str(cfg.abs_test_root), "log": [], "errors": []}


def test_audit_graph_populates_test_attribution(tmp_path):
    cfg = _audit_cfg(_ctx_project(tmp_path))
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    ta = out.get("test_attribution")
    assert ta is not None and ta["have_contexts"] is True
    assert ta["tests_seen"] >= 3  # test_ok, test_failure_path, test_double


def test_audit_toggle_off_skips_attribution(tmp_path):
    """End-to-end degrade lock: with the toggle off, the full audit+builder
    path reproduces Phase G exactly (engine-only numerator, no fake zeros)."""
    cfg = _audit_cfg(_ctx_project(tmp_path))
    cfg.audit.test_contexts = False
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    assert "test_attribution" not in out  # dimension falls back to engine-only
    report = build_unified_report({**_audit_state(cfg), **out, "generated": []}, cfg)
    if report.boundaries_total:  # fetch/double may or may not classify; if so:
        assert report.boundaries_covered == 0  # no engine tests -> Phase G zero
        assert report.boundaries_executed_only == 0
        dim = next(d for d in report.dimensions if d.name.startswith("system"))
        assert dim.detail["attribution"] == "engine-only"


# --- builder verdicts ---------------------------------------------------------

def _builder_state(**extra) -> dict:
    return {"project_root": ".", "source_root": "src", "test_root": "tests", **extra}


BOUNDARIES = {"boundaries": [
    {"module": "m", "function_name": "f1", "boundary_type": "http_handler"},
    {"module": "m", "function_name": "f2", "boundary_type": "env_reader"},
]}


def test_builder_covered_vs_executed_only():
    state = _builder_state(
        boundary_report=BOUNDARIES,
        test_attribution={"have_contexts": True, "tests_seen": 2, "boundaries": [
            {"module": "m", "function_name": "f1",
             "covering_tests": ["tests.test_a.test_asserts"]},
            {"module": "m", "function_name": "f2",
             "covering_tests": ["test_b.test_noassert"]},
        ]},
        assertion_report={"scores": [
            {"test_file": "/p/tests/test_a.py", "test_function": "test_asserts",
             "has_meaningful_assertion": True},
            {"test_file": "/p/tests/test_b.py", "test_function": "test_noassert",
             "has_meaningful_assertion": False},
        ]},
        generated=[],
    )
    report = build_unified_report(state, Config())
    assert report.boundaries_total == 2
    assert report.boundaries_covered == 1        # f1: asserting test ran it
    assert report.boundaries_executed_only == 1  # f2: ran, nothing asserted
    assert report.boundary_coverage_pct == 50.0
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.status is DimensionStatus.warn
    assert dim.detail["attribution"] == "contexts"
    assert any("f2" in s for s in dim.detail["executed_only_sample"])
    assert dim.detail["untested_sample"] == []


def test_builder_all_asserted_passes():
    state = _builder_state(
        boundary_report={"boundaries": [BOUNDARIES["boundaries"][0]]},
        test_attribution={"have_contexts": True, "tests_seen": 1, "boundaries": [
            {"module": "m", "function_name": "f1",
             "covering_tests": ["test_a.test_asserts"]},
        ]},
        assertion_report={"scores": [
            {"test_file": "tests/test_a.py", "test_function": "test_asserts",
             "has_meaningful_assertion": True},
        ]},
        generated=[],
    )
    report = build_unified_report(state, Config())
    assert report.boundary_coverage_pct == 100.0
    assert report.boundaries_executed_only == 0
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.status is DimensionStatus.passed


def test_builder_malformed_label_degrades_to_uncovered():
    """A dotless context label can't match any asserting test — the boundary
    reads executed_only (never a crash, never silent coverage)."""
    state = _builder_state(
        boundary_report={"boundaries": [BOUNDARIES["boundaries"][0]]},
        test_attribution={"have_contexts": True, "tests_seen": 1, "boundaries": [
            {"module": "m", "function_name": "f1", "covering_tests": ["oddlabel"]},
        ]},
        assertion_report={"scores": [
            {"test_file": "tests/test_a.py", "test_function": "oddlabel",
             "has_meaningful_assertion": True},
        ]},
        generated=[],
    )
    report = build_unified_report(state, Config())
    assert report.boundaries_covered == 0
    assert report.boundaries_executed_only == 1


def test_builder_engine_pass_lifts_without_assertion_join():
    """An engine-written record that passed the integrate gate counts as
    covered even if the contexts join sees only non-asserting tests — the gate
    already enforced green-run + scans."""
    state = _builder_state(
        boundary_report={"boundaries": [BOUNDARIES["boundaries"][0]]},
        test_attribution={"have_contexts": True, "tests_seen": 1, "boundaries": [
            {"module": "m", "function_name": "f1",
             "covering_tests": ["test_x.test_weak"]},
        ]},
        assertion_report={"scores": []},  # nothing asserts per the analyzer
        generated=[{"module": "m", "boundary_fn": "f1",
                    "test_path": "tests/pyverdex_integration/test_f1.py",
                    "gate": "pass"}],
    )
    report = build_unified_report(state, Config())
    assert report.boundaries_covered == 1
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.detail["engine_covered"] == 1


def test_builder_engine_only_fallback_preserves_phase_g():
    """No contexts (old DB / toggle off) -> the Phase G numerator and wording,
    with executed_only pinned to zero (no fake attribution)."""
    state = _builder_state(
        boundary_report=BOUNDARIES,
        generated=[{"module": "m", "boundary_fn": "f1",
                    "test_path": "tests/pyverdex_integration/test_f1.py",
                    "gate": "pass"}],
    )
    report = build_unified_report(state, Config())
    assert report.boundaries_covered == 1
    assert report.boundaries_executed_only == 0
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.detail["attribution"] == "engine-only"
    assert "passing integration test" in dim.headline  # Phase G wording kept
