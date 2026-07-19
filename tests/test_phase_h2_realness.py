"""Phase H2 — test-realness tiers: classifier, grading, degrade paths.

Locks the review-hardened rules: only dependency-replacing signals set a tier
(control signals like freezegun NEVER demote), tier = lowest rung touched,
``unknown`` grades as real-equivalent (demotion needs positive evidence), and
grading requires contexts so the engine-only fallback stays Phase G exact.
"""

from __future__ import annotations

from pathlib import Path

from pyverdex.config import Config
from pyverdex.models import DimensionStatus
from pyverdex.report.builder import build_unified_report
from pyverdex.skills import _realness
from pyverdex.skills.audit import build_audit_graph


def _classify(tmp_path: Path, test_src: str, conftest: str | None = None,
              subdir: str = "tests") -> dict[str, str]:
    """{test_id: tier} for one test file (+ optional conftest)."""
    tests = tmp_path / subdir
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_x.py").write_text(test_src, encoding="utf-8")
    if conftest is not None:
        (tests / "conftest.py").write_text(conftest, encoding="utf-8")
    report = _realness.classify_tests(tests, tmp_path)
    return {t["test_id"]: t["tier"] for t in report["tests"]}


# --- signal taxonomy ---------------------------------------------------------

def test_mock_signals_from_imports_and_calls(tmp_path):
    tiers = _classify(tmp_path, (
        "from unittest import mock\n"
        "from unittest.mock import patch\n"
        "import responses\n\n"
        "def test_patched():\n"
        "    with patch('svc.dep') as p:\n"
        "        assert p\n\n"
        "@responses.activate\n"
        "def test_http_stubbed():\n"
        "    assert True\n\n"
        "def test_untouched():\n"
        "    assert 1 + 1 == 2\n"
    ))
    assert tiers["test_x.test_patched"] == "mock"
    assert tiers["test_x.test_http_stubbed"] == "mock"
    # imports alone don't demote a test that never uses them
    assert tiers["test_x.test_untouched"] == "unknown"


def test_fake_in_process_and_real_tiers(tmp_path):
    tiers = _classify(tmp_path, (
        "import fakeredis\n"
        "from fastapi.testclient import TestClient\n"
        "import testcontainers.postgres\n\n"
        "def test_fake_store():\n"
        "    r = fakeredis.FakeRedis()\n"
        "    assert r is not None\n\n"
        "def test_in_process_api():\n"
        "    client = TestClient(object())\n"
        "    assert client is not None\n\n"
        "def test_real_db():\n"
        "    c = testcontainers.postgres.PostgresContainer()\n"
        "    assert c is not None\n"
    ))
    assert tiers["test_x.test_fake_store"] == "fake"
    assert tiers["test_x.test_in_process_api"] == "in_process"
    assert tiers["test_x.test_real_db"] == "real"


def test_control_signals_never_demote(tmp_path):
    """The review-hardened rule: freezegun + a real container is a REAL test;
    freezegun alone is unknown (not mock)."""
    tiers = _classify(tmp_path, (
        "import freezegun\n"
        "import testcontainers.postgres\n\n"
        "@freezegun.freeze_time('2026-01-01')\n"
        "def test_frozen_real_db():\n"
        "    c = testcontainers.postgres.PostgresContainer()\n"
        "    assert c is not None\n\n"
        "@freezegun.freeze_time('2026-01-01')\n"
        "def test_frozen_logic():\n"
        "    assert 1 + 1 == 2\n"
    ))
    assert tiers["test_x.test_frozen_real_db"] == "real"
    assert tiers["test_x.test_frozen_logic"] == "unknown"


def test_decorator_only_signal_is_caught(tmp_path):
    """A tiered signal used ONLY in the decorator list (no body use) tiers the
    test — decorators are part of the function node walk."""
    tiers = _classify(tmp_path, (
        "from unittest.mock import patch\n\n"
        "@patch('svc.dep')\n"
        "def test_decorated(dep):\n"
        "    assert dep is not None\n"
    ))
    assert tiers["test_x.test_decorated"] == "mock"


def test_lowest_rung_wins(tmp_path):
    """A test that mocks one dependency and containers another is mock-tier —
    the weakest link grades the test."""
    tiers = _classify(tmp_path, (
        "from unittest.mock import patch\n"
        "import testcontainers.postgres\n\n"
        "def test_mixed():\n"
        "    with patch('svc.dep'):\n"
        "        c = testcontainers.postgres.PostgresContainer()\n"
        "        assert c is not None\n"
    ))
    assert tiers["test_x.test_mixed"] == "mock"


# --- fixture resolution ------------------------------------------------------

def test_plugin_fixture_registry_and_neutral_fixtures(tmp_path):
    tiers = _classify(tmp_path, (
        "def test_monkeypatched(monkeypatch):\n"
        "    monkeypatch.setenv('KEY', 'x')\n"
        "    assert True\n\n"
        "def test_tmp_only(tmp_path):\n"
        "    assert tmp_path is not None\n"
    ))
    assert tiers["test_x.test_monkeypatched"] == "mock"
    assert tiers["test_x.test_tmp_only"] == "unknown"  # tmp_path is neutral


def test_conftest_fixture_resolution_transitive(tmp_path):
    """A requested fixture defined in conftest carries its signals, including
    through fixture->fixture dependencies."""
    tiers = _classify(tmp_path, (
        "def test_via_fixture(api_client):\n"
        "    assert api_client is not None\n"
    ), conftest=(
        "import pytest\n"
        "from fastapi.testclient import TestClient\n\n"
        "@pytest.fixture\n"
        "def app():\n"
        "    return object()\n\n"
        "@pytest.fixture\n"
        "def api_client(app):\n"
        "    return TestClient(app)\n"
    ))
    assert tiers["test_x.test_via_fixture"] == "in_process"


def test_local_fixture_shadows_conftest(tmp_path):
    """pytest semantics: a fixture in the test module wins over conftest."""
    tiers = _classify(tmp_path, (
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def store():\n"
        "    return {}\n\n"  # plain dict, no signals -> unknown
        "def test_local_store(store):\n"
        "    assert store == {}\n"
    ), conftest=(
        "import pytest\n"
        "import fakeredis\n\n"
        "@pytest.fixture\n"
        "def store():\n"
        "    return fakeredis.FakeRedis()\n"
    ))
    assert tiers["test_x.test_local_store"] == "unknown"


def test_autouse_replacement_is_a_caveat_not_a_tier(tmp_path):
    """Dogfood-driven rule: ONE autouse harness stub must not demote the whole
    suite to mock (it collapsed 162/162 of pyverdex's own tests — zero
    discrimination). Autouse replacement is recorded as a suite caveat and on
    each test's signals, but only signals the test itself uses/requests tier it."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "def test_anything():\n"
        "    assert True\n", encoding="utf-8")
    (tests / "conftest.py").write_text(
        "import pytest\n"
        "from unittest.mock import patch\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def _stub_everything():\n"
        "    with patch('svc.dep'):\n"
        "        yield\n", encoding="utf-8")
    report = _realness.classify_tests(tests, tmp_path)
    rec = next(t for t in report["tests"] if t["test_id"] == "test_x.test_anything")
    assert rec["tier"] == "unknown"  # not demoted by ambient policy
    assert any(s.startswith("autouse:") for s in rec["signals"])  # but visible
    assert report["autouse_replacements"]  # and rolled up as a suite caveat


def test_fixture_cycle_and_unresolvable_do_not_crash(tmp_path):
    tiers = _classify(tmp_path, (
        "def test_cyclic(a):\n"
        "    assert True\n\n"
        "def test_unresolvable(no_such_fixture):\n"
        "    assert True\n"
    ), conftest=(
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def a(b):\n"
        "    return b\n\n"
        "@pytest.fixture\n"
        "def b(a):\n"
        "    return a\n"
    ))
    assert tiers["test_x.test_cyclic"] == "unknown"
    assert tiers["test_x.test_unresolvable"] == "unknown"


def test_fixture_functions_are_not_classified_as_tests(tmp_path):
    """A @pytest.fixture named test_* (rare but legal) must not be a record."""
    tiers = _classify(tmp_path, (
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def test_data():\n"
        "    return 1\n\n"
        "def test_uses_it(test_data):\n"
        "    assert test_data == 1\n"
    ))
    assert "test_x.test_data" not in tiers
    assert tiers["test_x.test_uses_it"] == "unknown"


# --- audit-graph integration -------------------------------------------------

def _boundary_project(tmp_path: Path) -> Path:
    """env_reader boundary + one mocked test and one plain asserting test."""
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
    pkg = tmp_path / "src" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "api.py").write_text(
        "import os\n\n"
        "def handler(flag):\n"
        "    return os.environ.get('KEY', 'x') if flag else 'off'\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_api.py").write_text(
        "from svc.api import handler\n\n"
        "def test_handler_env_mocked(monkeypatch):\n"
        "    monkeypatch.setenv('KEY', 'v')\n"
        "    assert handler(1) == 'v'\n",
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


def test_audit_populates_realness_and_grades_mock_only(tmp_path):
    """Full pipeline: the only asserting test monkeypatches the env, so the
    env_reader boundary grades mock_only end-to-end."""
    cfg = _audit_cfg(_boundary_project(tmp_path))
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    rr = out.get("realness_report")
    assert rr is not None and rr["have_report"]
    tiers = {t["test_id"]: t["tier"] for t in rr["tests"]}
    assert tiers["test_api.test_handler_env_mocked"] == "mock"

    report = build_unified_report({**_audit_state(cfg), **out, "generated": []}, cfg)
    assert report.boundaries_total >= 1
    assert report.boundaries_mock_only == report.boundaries_total
    assert report.boundaries_real_covered == 0
    assert report.boundary_realness_pct == 0.0
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.detail["attribution"] == "contexts+realness"
    assert any("handler" in s for s in dim.detail["mock_only_sample"])


def test_audit_realness_toggle_off_leaves_grading_out(tmp_path):
    cfg = _audit_cfg(_boundary_project(tmp_path))
    cfg.audit.realness = False
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    assert "realness_report" not in out
    report = build_unified_report({**_audit_state(cfg), **out, "generated": []}, cfg)
    assert report.boundary_realness_pct is None  # ungraded, H1 shape
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.detail["attribution"] == "contexts"


# --- builder grading (synthetic) ---------------------------------------------

def _builder_state(**extra) -> dict:
    return {"project_root": ".", "source_root": "src", "test_root": "tests", **extra}


def _graded_state(tier: str) -> dict:
    return _builder_state(
        boundary_report={"boundaries": [
            {"module": "m", "function_name": "f1", "boundary_type": "http_handler"}]},
        test_attribution={"have_contexts": True, "tests_seen": 1, "boundaries": [
            {"module": "m", "function_name": "f1",
             "covering_tests": ["test_a.test_it"]}]},
        assertion_report={"scores": [
            {"test_file": "tests/test_a.py", "test_function": "test_it",
             "has_meaningful_assertion": True}]},
        realness_report={"have_report": True, "tests": [
            {"test_id": "test_a.test_it", "tier": tier}]},
        generated=[],
    )


def test_builder_grades_real_mock_and_unknown():
    for tier, expect_real in (("real", True), ("in_process", True),
                              ("unknown", True),  # demote only on evidence
                              ("mock", False), ("fake", False)):
        report = build_unified_report(_graded_state(tier), Config())
        assert report.boundaries_covered == 1, tier
        assert (report.boundaries_real_covered == 1) is expect_real, tier
        assert (report.boundaries_mock_only == 1) is not expect_real, tier
    r = build_unified_report(_graded_state("real"), Config())
    assert r.boundary_realness_pct == 100.0
    dim = next(d for d in r.dimensions if d.name.startswith("system"))
    assert "real-tested" in dim.headline


def test_builder_best_covering_tier_wins():
    """One mock test AND one real test covering the same boundary -> the best
    rung grades it (the boundary IS verified against the real dependency)."""
    state = _graded_state("mock")
    state["test_attribution"]["boundaries"][0]["covering_tests"].append(
        "test_b.test_real")
    state["assertion_report"]["scores"].append(
        {"test_file": "tests/test_b.py", "test_function": "test_real",
         "has_meaningful_assertion": True})
    state["realness_report"]["tests"].append(
        {"test_id": "test_b.test_real", "tier": "real"})
    report = build_unified_report(state, Config())
    assert report.boundaries_real_covered == 1
    assert report.boundaries_mock_only == 0


def test_builder_no_contexts_means_no_grading():
    """Realness without contexts must not grade — the engine-only fallback
    stays Phase G exact (locked in test_phase_h_contexts too)."""
    state = _builder_state(
        boundary_report={"boundaries": [
            {"module": "m", "function_name": "f1", "boundary_type": "http_handler"}]},
        realness_report={"have_report": True, "tests": [
            {"test_id": "test_a.test_it", "tier": "mock"}]},
        generated=[{"module": "m", "boundary_fn": "f1",
                    "test_path": "tests/pyverdex_integration/t.py", "gate": "pass"}],
    )
    report = build_unified_report(state, Config())
    assert report.boundaries_covered == 1  # engine join, Phase G semantics
    assert report.boundary_realness_pct is None
    assert report.boundaries_mock_only == 0
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.detail["attribution"] == "engine-only"
    assert "passing integration test" in dim.headline


def test_builder_engine_lift_stays_ungraded_covered():
    """Engine-covered boundary with no attributed asserting test: covered, but
    neither real_covered nor mock_only (no data is not mock evidence)."""
    state = _graded_state("mock")
    # the attributed covering test does NOT assert -> not an asserting test
    state["assertion_report"]["scores"][0]["has_meaningful_assertion"] = False
    state["generated"] = [{"module": "m", "boundary_fn": "f1",
                           "test_path": "tests/pyverdex_integration/t.py",
                           "gate": "pass"}]
    report = build_unified_report(state, Config())
    assert report.boundaries_covered == 1
    assert report.boundaries_real_covered == 0
    assert report.boundaries_mock_only == 0
    # review-hardened: with zero graded verdicts the realness pct must be None
    # (a "0% real" claim here would be a fake zero) and the headline falls
    # back to the ungraded H1 form
    assert report.boundary_realness_pct is None
    dim = next(d for d in report.dimensions if d.name.startswith("system"))
    assert dim.status is DimensionStatus.passed  # covered is covered
    assert "asserting test" in dim.headline
