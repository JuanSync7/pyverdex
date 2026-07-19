"""Phase I — failure-path coverage + boot smoke.

Locks the ADR 0008 semantics: one except-handler *body* = one handler
(clause lines excluded), multiple/nested handlers counted separately,
finally/else excluded, re-raise counts when executed, no-handler boundaries
excluded from the denominator but surfaced as the unprotected worklist; and
the boot signal: composition-root factories detected by name or framework-app
construction, executed iff any body line ran under a test. Both degrade to
mapped-not-measured (never fake zeros) without coverage data.
"""

from __future__ import annotations

from pathlib import Path

from pyverdex.config import Config
from pyverdex.models import DimensionStatus
from pyverdex.report.builder import build_unified_report
from pyverdex.skills import _boot, _detect, _failpaths
from pyverdex.skills.audit import build_audit_graph
from pyverdex.tools import adapters


# --- handler enumeration (pure AST) ------------------------------------------

def _handlers_for(tmp_path: Path, src: str) -> dict[tuple[str, str], list[set[int]]]:
    pkg = tmp_path / "src" / "m"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(src, encoding="utf-8")
    return _failpaths.boundary_handlers(
        tmp_path / "src", [{"module": "m.mod", "function_name": "f"}])


def test_handler_semantics_multiple_nested_finally_else(tmp_path):
    handlers = _handlers_for(tmp_path, (
        "def f(dep):\n"
        "    try:\n"                      # 2
        "        v = dep()\n"             # 3
        "    except KeyError:\n"          # 4
        "        try:\n"                  # 5   nested try INSIDE a handler
        "            v = dep()\n"         # 6
        "        except RuntimeError:\n"  # 7
        "            v = None\n"          # 8   nested handler body
        "    except ValueError:\n"        # 9
        "        v = 0\n"                 # 10  second handler of outer try
        "    else:\n"                     # 11
        "        v = v + 1\n"             # 12  else: NOT a handler
        "    finally:\n"                  # 13
        "        dep = None\n"            # 14  finally: NOT a handler
        "    return v\n"
    ))[("m.mod", "f")]
    # outer KeyError handler + nested RuntimeError handler + outer ValueError
    assert len(handlers) == 3
    all_lines = set().union(*handlers)
    assert 12 not in all_lines and 14 not in all_lines  # else/finally excluded
    # outer except CLAUSE lines excluded: they execute on a type-test even
    # when their handler body never runs, so they'd inflate the numerator.
    # (The NESTED clause line 7 legitimately sits inside the OUTER handler's
    # body-span — executing it implies the outer handler ran, which is the
    # exact invariant a handler line-set must satisfy.)
    assert 4 not in all_lines and 9 not in all_lines
    assert {8} in handlers and {10} in handlers  # nested + second handler bodies
    # the KeyError handler's body is the nested try statement's span
    assert any(5 in h and 8 in h for h in handlers)


def test_except_star_handlers_are_counted(tmp_path):
    """PEP 654 exception-group handlers (ast.TryStar) must not silently
    vanish from the denominator (review blocker: data loss on py3.11+)."""
    handlers = _handlers_for(tmp_path, (
        "def f(dep):\n"
        "    try:\n"
        "        dep()\n"
        "    except* KeyError:\n"
        "        a = 1\n"          # 5
        "    except* ValueError:\n"
        "        b = 2\n"          # 7
        "    return 0\n"
    ))[("m.mod", "f")]
    assert len(handlers) == 2
    assert {5} in handlers and {7} in handlers


def test_no_handlers_is_unprotected_not_denominator(tmp_path):
    pkg = tmp_path / "src" / "m"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    report = _failpaths.failure_path_report(
        tmp_path, tmp_path / "src", [{"module": "m.mod", "function_name": "f"}])
    assert report["total"] == 0  # not in the ratio
    assert report["unprotected_total"] == 1  # but loudly surfaced
    assert report["unprotected"] == [{"module": "m.mod", "function_name": "f"}]


def test_unparseable_module_degrades_silently(tmp_path):
    (tmp_path / "src").mkdir()
    report = _failpaths.failure_path_report(
        tmp_path, tmp_path / "src", [{"module": "ghost", "function_name": "f"}])
    assert report["total"] == 0 and report["unprotected_total"] == 0


# --- end-to-end: real coverage run, forced exception attribution -------------

API_SRC = """\
import os


def handler(key):
    try:
        return os.environ[key]
    except KeyError:
        return "default"
"""


def _fail_project(tmp_path: Path, force_failure: bool) -> Path:
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
    pkg = tmp_path / "src" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "api.py").write_text(API_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    body = (
        "from svc.api import handler\n\n"
        "def test_present(monkeypatch):\n"
        "    monkeypatch.setenv('K', 'v')\n"
        "    assert handler('K') == 'v'\n"
    )
    if force_failure:
        body += (
            "\ndef test_missing(monkeypatch):\n"
            "    monkeypatch.delenv('K', raising=False)\n"
            "    assert handler('K') == 'default'\n"
        )
    (tests / "test_api.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_forced_exception_covers_failure_path_with_forcing_test(tmp_path):
    root = _fail_project(tmp_path, force_failure=True)
    res = adapters.collect_coverage(root, root / "src", root / "tests",
                                    dynamic_contexts=True)
    assert res.returncode in (0, 1)
    report = _failpaths.failure_path_report(
        root, root / "src", [{"module": "svc.api", "function_name": "handler"}])
    assert report["have_coverage"] and report["total"] == 1
    rec = report["boundaries"][0]
    assert rec["covered"] is True and rec["handlers_covered"] == 1
    # the H1-spike mechanism: the handler attributes to the FORCING test only
    assert rec["forcing_tests"] == ["test_api.test_missing"]


def test_unforced_exception_is_uncovered_failure_path(tmp_path):
    root = _fail_project(tmp_path, force_failure=False)
    res = adapters.collect_coverage(root, root / "src", root / "tests",
                                    dynamic_contexts=True)
    assert res.returncode in (0, 1)
    report = _failpaths.failure_path_report(
        root, root / "src", [{"module": "svc.api", "function_name": "handler"}])
    rec = report["boundaries"][0]
    assert rec["covered"] is False and rec["forcing_tests"] == []


def test_failure_report_degrades_without_coverage(tmp_path):
    root = _fail_project(tmp_path, force_failure=True)  # no coverage run
    report = _failpaths.failure_path_report(
        root, root / "src", [{"module": "svc.api", "function_name": "handler"}])
    assert report["have_coverage"] is False
    assert report["covered"] is None  # mapped, not measured
    assert report["boundaries"][0]["covered"] is None


# --- boot smoke ---------------------------------------------------------------

def test_detect_app_factories_by_name_and_constructor(tmp_path):
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "__init__.py").write_text("", encoding="utf-8")
    (src / "app" / "wiring.py").write_text(
        "class FastAPI:\n    pass\n\n\n"
        "def create_app():\n    return object()\n\n\n"
        "def assemble():\n    return FastAPI()\n\n\n"
        "def helper():\n    return 1\n",
        encoding="utf-8",
    )
    # a vendored tree's main() must NOT read as a composition root
    vend = src / "app" / "vendored" / "tool"
    vend.mkdir(parents=True)
    (vend / "tool.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    factories = _detect.detect_app_factories(src)
    by_name = {f["function_name"]: f["reason"] for f in factories}
    assert by_name == {"create_app": "factory-name",
                       "assemble": "constructs:FastAPI"}


def test_nested_def_construction_is_not_the_outer_factory(tmp_path):
    """A helper factory DEFINED INSIDE a plain function must not mark the
    outer function as the composition root (review finding); construction
    under if/with inside the factory's own body still counts."""
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "__init__.py").write_text("", encoding="utf-8")
    (src / "app" / "wiring.py").write_text(
        "class FastAPI:\n    pass\n\n\n"
        "def outer_plain():\n"
        "    def inner_factory():\n"
        "        return FastAPI()\n"
        "    return inner_factory\n\n\n"
        "def conditional_factory(flag):\n"
        "    if flag:\n"
        "        return FastAPI()\n"
        "    return None\n",
        encoding="utf-8",
    )
    by_name = {f["function_name"]: f["reason"]
               for f in _detect.detect_app_factories(src)}
    assert "outer_plain" not in by_name
    assert by_name == {"conditional_factory": "constructs:FastAPI"}


def test_decorated_factory_body_start_skips_decorator_and_def(tmp_path):
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "__init__.py").write_text("", encoding="utf-8")
    (src / "app" / "wiring.py").write_text(
        "def deco(f):\n    return f\n\n\n"
        "@deco\n"                       # 5
        "def create_app():\n"           # 6
        "    return {'ok': True}\n",    # 7
        encoding="utf-8",
    )
    fac = next(f for f in _detect.detect_app_factories(src)
               if f["function_name"] == "create_app")
    assert fac["body_start"] == 7  # neither the decorator nor the def line


def _boot_project(tmp_path: Path, call_factory: bool) -> Path:
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
    pkg = tmp_path / "src" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "wiring.py").write_text(
        "def create_app():\n    return {'wired': True}\n\n\n"
        "def helper():\n    return 1\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    body = "from svc.wiring import create_app, helper\n\n"
    body += ("def test_boot():\n    assert create_app()['wired']\n"
             if call_factory else
             "def test_helper():\n    assert helper() == 1\n")
    (tests / "test_api.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_boot_report_executed_with_test_attribution(tmp_path):
    root = _boot_project(tmp_path, call_factory=True)
    adapters.collect_coverage(root, root / "src", root / "tests",
                              dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["total"] == 1 and br["executed"] == 1
    assert br["factories"][0]["tests"] == ["test_api.test_boot"]


def test_boot_report_unexecuted_factory(tmp_path):
    root = _boot_project(tmp_path, call_factory=False)
    adapters.collect_coverage(root, root / "src", root / "tests",
                              dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["total"] == 1 and br["executed"] == 0
    assert br["factories"][0]["executed"] is False


# --- audit-graph integration --------------------------------------------------

def _audit_cfg(project: Path) -> Config:
    cfg = Config()
    cfg.project_root = str(project)
    cfg.paths.source_root = "src"
    cfg.paths.test_root = "tests"
    return cfg


def _audit_state(cfg: Config) -> dict:
    return {"project_root": str(cfg.root), "source_root": str(cfg.abs_source_root),
            "test_root": str(cfg.abs_test_root), "log": [], "errors": []}


def test_audit_populates_failure_and_boot_reports(tmp_path):
    """Real audit graph on a project with an env boundary (handled + forced)
    and a factory called by a test — both reports land in state and flow into
    the report dimensions + fields."""
    root = _fail_project(tmp_path, force_failure=True)
    (root / "src" / "svc" / "wiring.py").write_text(
        "def create_app():\n    return {'wired': True}\n", encoding="utf-8")
    (root / "tests" / "test_boot.py").write_text(
        "from svc.wiring import create_app\n\n"
        "def test_boot():\n    assert create_app()['wired']\n", encoding="utf-8")
    cfg = _audit_cfg(root)
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))

    fp = out.get("failure_path_report")
    assert fp is not None and fp["have_coverage"]
    br = out.get("boot_report")
    assert br is not None and br["executed"] == br["total"] == 1

    report = build_unified_report({**_audit_state(cfg), **out, "generated": []}, cfg)
    assert report.app_factories_total == 1
    assert report.app_factories_executed == 1
    boot_dim = next(d for d in report.dimensions if d.name.startswith("boot"))
    assert boot_dim.status is DimensionStatus.passed
    if report.failure_paths_total:  # env boundary detected & handled
        assert report.failure_path_coverage_pct == 100.0
        fp_dim = next(d for d in report.dimensions if d.name == "failure-path")
        assert fp_dim.status is DimensionStatus.passed


def test_audit_toggles_off_skip_both(tmp_path):
    root = _fail_project(tmp_path, force_failure=True)
    cfg = _audit_cfg(root)
    cfg.audit.failure_paths = False
    cfg.audit.boot_smoke = False
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    assert "failure_path_report" not in out
    assert "boot_report" not in out


# --- builder dimensions (synthetic) ------------------------------------------

def _builder_state(**extra) -> dict:
    return {"project_root": ".", "source_root": "src", "test_root": "tests", **extra}


def test_builder_failure_path_dimension_and_worklists():
    state = _builder_state(failure_path_report={
        "have_coverage": True, "total": 2, "covered": 1,
        "unprotected_total": 1,
        "unprotected": [{"module": "m", "function_name": "naked"}],
        "boundaries": [
            {"module": "m", "function_name": "ok", "handlers_total": 1,
             "handlers_covered": 1, "covered": True,
             "forcing_tests": ["test_a.test_boom"]},
            {"module": "m", "function_name": "unhit", "handlers_total": 2,
             "handlers_covered": 0, "covered": False, "forcing_tests": []},
        ],
    })
    report = build_unified_report(state, Config())
    assert report.failure_paths_total == 2
    assert report.failure_paths_covered == 1
    assert report.failure_path_coverage_pct == 50.0
    assert report.boundaries_unprotected == 1
    dim = next(d for d in report.dimensions if d.name == "failure-path")
    assert dim.status is DimensionStatus.warn
    assert dim.detail["uncovered_sample"] == ["m.unhit"]
    assert dim.detail["unprotected_sample"] == ["m.naked"]
    assert "1 boundaries unprotected" in dim.headline


def test_builder_failure_path_not_run_without_coverage():
    state = _builder_state(failure_path_report={
        "have_coverage": False, "total": 3, "covered": None,
        "unprotected_total": 0, "unprotected": [],
        "boundaries": [{"module": "m", "function_name": "f", "handlers_total": 1,
                        "handlers_covered": None, "covered": None,
                        "forcing_tests": []}] * 3,
    })
    report = build_unified_report(state, Config())
    assert report.failure_path_coverage_pct is None  # mapped != measured
    assert report.failure_paths_covered == 0
    dim = next(d for d in report.dimensions if d.name == "failure-path")
    assert dim.status is DimensionStatus.not_run


def test_builder_boot_dimension_absent_when_no_factories():
    report = build_unified_report(_builder_state(), Config())
    assert report.app_factories_total == 0
    assert report.app_factories_executed is None
    assert not any(d.name.startswith("boot") for d in report.dimensions)
    assert not any(d.name == "failure-path" for d in report.dimensions)


def test_builder_boot_warns_on_unexecuted_factory():
    state = _builder_state(boot_report={
        "have_coverage": True, "total": 2, "executed": 1,
        "factories": [
            {"module": "a.wiring", "function_name": "create_app",
             "line_start": 1, "line_end": 2, "reason": "factory-name",
             "executed": True, "tests": ["test_boot.test_it"]},
            {"module": "b.wiring", "function_name": "main",
             "line_start": 1, "line_end": 2, "reason": "factory-name",
             "executed": False, "tests": []},
        ],
    })
    report = build_unified_report(state, Config())
    assert report.app_factories_total == 2
    assert report.app_factories_executed == 1
    dim = next(d for d in report.dimensions if d.name.startswith("boot"))
    assert dim.status is DimensionStatus.warn
    assert dim.detail["unexecuted_sample"] == ["b.wiring.main"]
