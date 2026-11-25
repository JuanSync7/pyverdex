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
    found = _failpaths.boundary_handlers(
        tmp_path / "src", [{"module": "m.mod", "function_name": "f"}])
    return {key: [set(a.lines) for a in anchors] for key, anchors in found.items()}


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


def test_decorated_factory_anchor_skips_decorator_and_def(tmp_path):
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
    # neither the decorator nor the def line
    assert fac["body_lines"] == [7] and fac["entry_line"] == 7


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
    assert report.failure_paths_total == 1  # env boundary detected & handled
    assert report.failure_path_coverage_pct == 100.0
    fp_dim = next(d for d in report.dimensions if d.name == "failure-path")
    assert fp_dim.status is DimensionStatus.passed


def test_audit_toggles_off_skip_both(tmp_path):
    root = _fail_project(tmp_path, force_failure=True)
    cfg = _audit_cfg(root)
    cfg.audit.failure_paths = False
    cfg.audit.boot_smoke = False
    out = build_audit_graph(cfg).invoke(_audit_state(cfg))
    # written as None, not left out: a key left out keeps an earlier value
    assert out["failure_path_report"] is None
    assert out["boot_report"] is None


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


# --- review findings: a pass must mean "a test did it" -------------------------

def _mini_project(tmp_path: Path, module_src: str, test_src: str) -> Path:
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
    pkg = tmp_path / "src" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(module_src, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_text(test_src, encoding="utf-8")
    return tmp_path


_USES_OTHER = ("from svc.mod import other\n\n"
               "def test_other():\n    assert other() == 1\n")
_BND = [{"module": "svc.mod", "function_name": "f"}]


def test_boot_one_line_factory_only_imported_is_not_executed(tmp_path):
    """The body shares the def line, which runs at import: unmeasurable by
    line, so it must never read as executed."""
    root = _mini_project(
        tmp_path, "def create_app(): return {}\n\n\ndef other():\n    return 1\n",
        _USES_OTHER)
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["total"] == 1
    assert br["executed"] == 0
    assert br["factories"][0]["executed"] is None


def test_boot_factory_called_only_at_import_is_not_executed_by_a_test(tmp_path):
    root = _mini_project(
        tmp_path,
        "def create_app():\n    return {}\n\n\napp = create_app()\n\n\n"
        "def other():\n    return 1\n",
        _USES_OTHER)
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["executed"] == 0
    assert br["factories"][0]["executed"] is False
    assert br["factories"][0]["tests"] == []


def test_boot_without_per_test_contexts_is_not_measured(tmp_path):
    """Without per-test contexts 'ran under a test' cannot be told from 'ran
    at import', so the report is mapped-not-measured."""
    root = _boot_project(tmp_path, call_factory=True)
    adapters.collect_coverage(root, root / "src", root / "tests",
                              dynamic_contexts=False)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] is False and br["executed"] is None
    assert br["factories"][0]["executed"] is None


def test_inline_except_body_is_not_covered_by_the_type_test(tmp_path):
    root = _mini_project(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        raise TypeError()\n"
        "    except ValueError: return 0\n",
        "import pytest\nfrom svc.mod import f\n\n"
        "def test_f():\n    with pytest.raises(TypeError):\n        f()\n")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["have_coverage"] and report["total"] == 1
    assert report["covered"] == 0
    # no line of its own to measure: unknown, neither covered nor a zero
    assert report["boundaries"][0]["covered"] is None


def test_handler_run_only_at_import_is_not_covered(tmp_path):
    root = _mini_project(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        return {}['k']\n"
        "    except KeyError:\n"
        "        return None\n\n\n"
        "AT_IMPORT = f()\n\n\n"
        "def other():\n    return 1\n",
        _USES_OTHER)
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["have_coverage"] and report["total"] == 1
    assert report["boundaries"][0]["covered"] is False


def test_failure_report_without_per_test_contexts_is_not_measured(tmp_path):
    root = _fail_project(tmp_path, force_failure=True)
    adapters.collect_coverage(root, root / "src", root / "tests",
                              dynamic_contexts=False)
    report = _failpaths.failure_path_report(
        root, root / "src", [{"module": "svc.api", "function_name": "handler"}])
    assert report["have_coverage"] is False and report["covered"] is None
    assert report["boundaries"][0]["covered"] is None


def test_nested_function_handler_does_not_protect_the_outer_boundary(tmp_path):
    handlers = _handlers_for(tmp_path, (
        "def f(dep):\n"
        "    def helper():\n"
        "        try:\n"
        "            return {}['k']\n"
        "        except KeyError:\n"
        "            return None\n"
        "    class K:\n"
        "        def m(self):\n"
        "            try:\n"
        "                return 1\n"
        "            except ValueError:\n"
        "                return 2\n"
        "    return dep(), helper, K\n"
    ))[("m.mod", "f")]
    assert handlers == []
    report = _failpaths.failure_path_report(
        tmp_path, tmp_path / "src", [{"module": "m.mod", "function_name": "f"}])
    assert report["total"] == 0 and report["unprotected_total"] == 1


def test_builder_unprotected_only_keeps_the_worklist_and_does_not_blame_coverage():
    state = _builder_state(failure_path_report={
        "have_coverage": True, "total": 0, "covered": 0,
        "unprotected_total": 1,
        "unprotected": [{"module": "m", "function_name": "f"}],
        "boundaries": [],
    })
    report = build_unified_report(state, Config())
    dim = next(d for d in report.dimensions if d.name == "failure-path")
    assert dim.status is DimensionStatus.warn
    assert "no coverage data" not in dim.headline
    assert "no per-test coverage data" not in dim.headline
    assert dim.detail["unprotected_sample"] == ["m.f"]
    assert report.failure_path_coverage_pct is None  # nothing to take a ratio of


def test_builder_not_run_keeps_the_unprotected_worklist():
    state = _builder_state(failure_path_report={
        "have_coverage": False, "total": 0, "covered": None,
        "unprotected_total": 1,
        "unprotected": [{"module": "m", "function_name": "f"}],
        "boundaries": [],
    })
    report = build_unified_report(state, Config())
    dim = next(d for d in report.dimensions if d.name == "failure-path")
    assert dim.status is DimensionStatus.not_run
    assert dim.detail["unprotected_sample"] == ["m.f"]


def test_audit_clears_reports_when_nothing_is_mapped(tmp_path):
    """The engine re-enters audit and state keys are last-write-wins: a scan
    that maps nothing must overwrite an earlier report, not leave it."""
    root = _mini_project(tmp_path, "def other():\n    return 1\n", _USES_OTHER)
    cfg = _audit_cfg(root)
    stale = {"have_coverage": True, "total": 1, "executed": 1, "covered": 1,
             "factories": [], "boundaries": [], "unprotected": [],
             "unprotected_total": 0}
    out = build_audit_graph(cfg).invoke(
        {**_audit_state(cfg), "boot_report": stale, "failure_path_report": stale})
    assert out["boot_report"] is None
    assert out["failure_path_report"] is None


# --- second review round -------------------------------------------------------

def test_static_coverage_label_is_not_a_test(tmp_path):
    """A target's own static coverage context labels import-time lines too;
    it must not read as a named test."""
    root = _mini_project(
        tmp_path,
        "def create_app():\n    return {}\n\n\n"
        "def f():\n"
        "    try:\n"
        "        return {}['k']\n"
        "    except KeyError:\n"
        "        return None\n\n\n"
        "app = create_app()\nAT_IMPORT = f()\n\n\n"
        "def other():\n    return 1\n",
        _USES_OTHER)
    (root / ".coveragerc").write_text("[run]\ncontext = ci\n", encoding="utf-8")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["executed"] == 0
    assert br["factories"][0]["executed"] is False
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["have_coverage"] and report["covered"] == 0
    assert report["boundaries"][0]["covered"] is False


def test_boot_nested_callable_run_by_a_test_does_not_credit_the_factory(tmp_path):
    root = _mini_project(
        tmp_path,
        "def create_app():\n"
        "    def app():\n"
        "        return 1\n"
        "    return app\n\n\n"
        "app = create_app()\n",
        "from svc.mod import app\n\n"
        "def test_app():\n    assert app() == 1\n")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["executed"] == 0
    # not credited; and not a measured zero either, because the factory's
    # first line is the nested def's line, which the nested callable also emits
    assert br["factories"][0]["executed"] is None


def test_nested_callable_in_handler_does_not_cover_the_outer_handler(tmp_path):
    root = _mini_project(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        return {}['missing']\n"
        "    except KeyError:\n"
        "        def recover():\n"
        "            try:\n"
        "                return {}['missing']\n"
        "            except KeyError:\n"
        "                return 1\n"
        "        return recover\n\n\n"
        "recover = f()\n",
        "from svc.mod import recover\n\n"
        "def test_recover():\n    assert recover() == 1\n")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["have_coverage"] and report["total"] == 1 and report["covered"] == 0
    # not covered; unknown rather than zero, because the handler's first line
    # is the nested def's line
    assert report["boundaries"][0]["covered"] is None


def test_multiline_except_header_is_not_a_handler_line(tmp_path):
    root = _mini_project(
        tmp_path,
        "def f(dep):\n"
        "    try:\n"
        "        return dep()\n"
        "    except (\n"
        "        ValueError): return 0\n",
        "import pytest\nfrom svc.mod import f\n\n"
        "def _boom():\n    raise TypeError()\n\n"
        "def test_f():\n    with pytest.raises(TypeError):\n        f(_boom)\n")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["have_coverage"] and report["covered"] == 0
    assert report["boundaries"][0]["covered"] is None


def test_builder_boot_unmeasurable_factory_is_not_a_measured_zero():
    fac = {"module": "a.wiring", "function_name": "create_app", "line_start": 1,
           "line_end": 1, "reason": "factory-name", "executed": None, "tests": []}
    state = _builder_state(boot_report={
        "have_coverage": True, "total": 1, "executed": 0, "factories": [fac]})
    report = build_unified_report(state, Config())
    assert report.app_factories_total == 1
    assert report.app_factories_executed is None
    dim = next(d for d in report.dimensions if d.name.startswith("boot"))
    assert dim.status is DimensionStatus.not_run
    assert dim.detail["unmeasurable_sample"] == ["a.wiring.create_app"]

    ran = {**fac, "module": "b.wiring", "line_end": 2, "executed": True,
           "tests": ["test_boot.test_it"]}
    state = _builder_state(boot_report={
        "have_coverage": True, "total": 2, "executed": 1, "factories": [fac, ran]})
    report = build_unified_report(state, Config())
    assert report.app_factories_executed == 1
    dim = next(d for d in report.dimensions if d.name.startswith("boot"))
    assert dim.status is DimensionStatus.warn  # one could not be measured
    assert dim.detail["unexecuted_sample"] == []
    assert dim.detail["unmeasurable_sample"] == ["a.wiring.create_app"]


def test_builder_failure_path_unmeasurable_boundary_is_not_a_measured_zero():
    unknown = {"module": "m", "function_name": "inline", "handlers_total": 1,
               "handlers_covered": None, "covered": None, "forcing_tests": []}
    state = _builder_state(failure_path_report={
        "have_coverage": True, "total": 1, "covered": 0,
        "unprotected_total": 0, "unprotected": [], "boundaries": [unknown]})
    report = build_unified_report(state, Config())
    assert report.failure_path_coverage_pct is None
    dim = next(d for d in report.dimensions if d.name == "failure-path")
    assert dim.status is DimensionStatus.not_run
    assert dim.detail["unmeasurable_sample"] == ["m.inline"]

    hit = {"module": "m", "function_name": "ok", "handlers_total": 1,
           "handlers_covered": 1, "covered": True, "forcing_tests": ["t.test_x"]}
    state = _builder_state(failure_path_report={
        "have_coverage": True, "total": 2, "covered": 1,
        "unprotected_total": 0, "unprotected": [], "boundaries": [unknown, hit]})
    report = build_unified_report(state, Config())
    assert report.failure_path_coverage_pct == 100.0  # 1 of 1 measurable
    dim = next(d for d in report.dimensions if d.name == "failure-path")
    assert dim.status is DimensionStatus.warn  # one could not be measured
    assert dim.detail["uncovered_sample"] == []
    assert dim.detail["unmeasurable_sample"] == ["m.inline"]


# --- third review round: real coverage runs, one per finding -------------------

def test_lambda_default_of_nested_helper_does_not_credit_factory_or_handler(tmp_path):
    root = _mini_project(
        tmp_path,
        "def create_app():\n"
        "    def helper(cb=lambda: 1):\n"
        "        return cb\n"
        "    return helper()\n\n\n"
        "def f():\n"
        "    try:\n"
        "        return {}['missing']\n"
        "    except KeyError:\n"
        "        def recover(cb=lambda: 2):\n"
        "            return cb\n"
        "        return recover()\n\n\n"
        "callback = create_app()\nfallback = f()\n",
        "from svc.mod import callback, fallback\n\n"
        "def test_callbacks():\n    assert callback() == 1 and fallback() == 2\n")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["executed"] == 0
    assert br["factories"][0]["executed"] is not True
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["have_coverage"] and report["covered"] == 0
    assert report["boundaries"][0]["covered"] is not True


def test_unmeasurable_handler_that_ran_does_not_make_the_boundary_a_zero(tmp_path):
    root = _mini_project(
        tmp_path,
        "def f(kind):\n"
        "    try:\n"
        "        raise kind()\n"
        "    except ValueError: return 1\n"
        "    except TypeError:\n"
        "        return 2\n",
        "from svc.mod import f\n\n"
        "def test_f():\n    assert f(ValueError) == 1\n")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    record = report["boundaries"][0]
    assert report["have_coverage"] and report["covered"] == 0
    assert record["covered"] is None  # the handler that ran cannot be judged
    assert record["handlers_unmeasurable"] == 1


def test_statement_spread_over_lines_is_seen_when_a_test_runs_it(tmp_path):
    root = _mini_project(
        tmp_path,
        "calls = []\n\n\n"
        "def create_app():\n"
        "    (\n"
        "        calls.append(1)\n"
        "    )\n\n\n"
        "def f():\n"
        "    try:\n"
        "        raise KeyError()\n"
        "    except KeyError:\n"
        "        (\n"
        "            calls.append(2)\n"
        "        )\n",
        "from svc.mod import calls, create_app, f\n\n"
        "def test_both():\n    create_app()\n    f()\n    assert calls == [1, 2]\n")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["executed"] == 1 and br["factories"][0]["executed"] is True
    assert br["factories"][0]["tests"] == ["test_mod.test_both"]
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["covered"] == 1 and report["boundaries"][0]["covered"] is True


_TWO_MODULES_TEST = ("from svc.mod import create_app, f\n"
                     "from svc.other import other\n\n"
                     "def test_all():\n"
                     "    assert create_app() == {} and f() is None and other() == 1\n")
_FACTORY_AND_BOUNDARY = (
    "def create_app():\n    return {}\n\n\n"
    "def f():\n"
    "    try:\n"
    "        return {}['k']\n"
    "    except KeyError:\n"
    "        return None\n")


def test_module_the_target_omits_from_coverage_is_unknown_not_zero(tmp_path):
    root = _mini_project(tmp_path, _FACTORY_AND_BOUNDARY, _TWO_MODULES_TEST)
    (root / "src" / "svc" / "other.py").write_text(
        "def other():\n    return 1\n", encoding="utf-8")
    (root / ".coveragerc").write_text("[run]\nomit = */svc/mod.py\n", encoding="utf-8")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["total"] == 1
    assert br["factories"][0]["executed"] is None and br["unmeasurable"] == 1
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["have_coverage"] and report["boundaries"][0]["covered"] is None
    unified = build_unified_report(
        {"project_root": str(root), "source_root": "src", "test_root": "tests",
         "boot_report": br, "failure_path_report": report}, Config())
    dims = {d.name: d for d in unified.dimensions}
    assert dims["boot (composition root)"].status == DimensionStatus.not_run
    assert dims["failure-path"].status == DimensionStatus.not_run


def test_module_no_test_imports_is_still_a_measured_zero(tmp_path):
    """The commonest true negative: nothing ever imports the app module. It
    must stay "not executed", not turn into unknown."""
    root = _mini_project(tmp_path, _FACTORY_AND_BOUNDARY,
                         "from svc.other import other\n\n"
                         "def test_other():\n    assert other() == 1\n")
    (root / "src" / "svc" / "other.py").write_text(
        "def other():\n    return 1\n", encoding="utf-8")
    adapters.collect_coverage(root, root / "src", root / "tests", dynamic_contexts=True)
    br = _boot.boot_report(root, root / "src")
    assert br["have_coverage"] and br["factories"][0]["executed"] is False
    report = _failpaths.failure_path_report(root, root / "src", _BND)
    assert report["boundaries"][0]["covered"] is False
