"""Phase E — breadth groundwork: semantic (import/AST) boundary detection that
replaces the filename heuristic, and the Runner protocol seam over pytest."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyverdex.config import Config, GateMode, StageConfig, StageName
from pyverdex.skills._detect import detect_framework
from pyverdex.skills.evaluate import _category, _classify_category, build_evaluate_graph
from pyverdex.tools import adapters
from pyverdex.tools.adapters import PytestRunner, ToolResult


def _src(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write {dotted_module: source} under a fresh source root and return it."""
    root = tmp_path / "src"
    for dotted, code in files.items():
        f = root.joinpath(*dotted.split(".")).with_suffix(".py")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code, encoding="utf-8")
    return root


# --- detect_framework: category from imports, not filename -----------------

@pytest.mark.parametrize("code,expected", [
    ("from sqlalchemy.orm import Session\n", "db"),
    ("import psycopg2\n", "db"),
    ("from django.db import models\n", "db"),
    ("from celery import shared_task\n", "queue"),
    ("import pika\n", "queue"),
    ("import click\n", "cli"),
    ("import typer\n", "cli"),
    ("import argparse\n", "cli"),
    ("from fastapi import FastAPI\n", "api"),
    ("import requests\n", "api"),
    ("import httpx\n", "api"),
])
def test_detect_framework_by_import(tmp_path, code, expected):
    root = _src(tmp_path, {"service": code})  # filename 'service' would default to api
    assert detect_framework("service", root) == expected


def test_detect_framework_precedence_db_over_api(tmp_path):
    root = _src(tmp_path, {"repo": "from sqlalchemy import text\nimport httpx\n"})
    assert detect_framework("repo", root) == "db"  # db outranks api


def test_detect_framework_none_without_framework(tmp_path):
    root = _src(tmp_path, {"plain": "x = 1\n"})
    assert detect_framework("plain", root) is None  # -> caller falls back


def test_detect_framework_ignores_relative_imports(tmp_path):
    # a project-local `from ..db import session` is NOT a framework signal
    root = _src(tmp_path, {"pkg.svc": "from ..db import session\n"})
    assert detect_framework("pkg.svc", root) is None


def test_detect_framework_resolves_package_init(tmp_path):
    root = _src(tmp_path, {"pkg.__init__": "import celery\n"})
    assert detect_framework("pkg", root) == "queue"


def test_detect_framework_missing_or_broken_file(tmp_path):
    root = _src(tmp_path, {"broken": "def (:\n"})  # syntax error
    assert detect_framework("broken", root) is None
    assert detect_framework("does_not_exist", root) is None


# --- _classify_category: semantic first, filename fallback -----------------

def test_classify_semantic_overrides_filename(tmp_path):
    # 'service' filename -> api by heuristic, but it imports sqlalchemy -> db
    root = _src(tmp_path, {"service": "import sqlalchemy\n"})
    assert _classify_category("service", root) == "db"
    assert _category("service") == "api"  # the heuristic alone would miss it


def test_classify_falls_back_to_filename_when_unresolved(tmp_path):
    root = _src(tmp_path, {})  # no file for this module
    # no source to parse -> detect returns None -> filename heuristic wins
    assert _classify_category("app.user_db_repo", root) == "db"
    assert _classify_category("app.handlers", root) == "api"


def test_evaluate_classify_uses_semantic_category(tmp_path):
    """End-to-end: a boundary gap whose module imports celery yields a queue
    candidate with the celery lifecycle pattern — despite a neutral filename."""
    root = _src(tmp_path, {"app.service": "from celery import Celery\n"})
    cfg = Config()
    cfg.stages = {n: StageConfig(enabled=True, gate=GateMode.auto) for n in StageName}
    graph = build_evaluate_graph(cfg)
    out = graph.invoke({
        "source_root": str(root),
        "audit_gap_report": {"gaps": [{
            "module": "app.service", "function_name": "enqueue",
            "coverage_pct": 40.0, "is_boundary": True}]},
        "integration_strategies": [], "approvals": {}, "log": [], "errors": [],
    })
    cand = out["integration_strategies"][0]["candidates"][0]
    assert cand["category"] == "queue"
    assert cand["pattern"] == "celery-test-harness"


# --- Runner protocol seam ---------------------------------------------------

def test_get_runner_default_and_unknown():
    r = adapters.get_runner()
    assert r.name == "pytest" and isinstance(r, PytestRunner)
    assert adapters.get_runner("pytest") is r  # registered singleton
    with pytest.raises(ValueError, match="unknown runner 'unittest'"):
        adapters.get_runner("unittest")


def test_config_runner_default_and_validation():
    assert Config().runner == "pytest"
    with pytest.raises(ValueError):
        Config(runner="nope")


class _RecordingRunner:
    """A stand-in Runner that records delegation instead of shelling out."""
    name = "recording"

    def __init__(self):
        self.calls: list[str] = []

    def collect_coverage(self, project_root, source_root, test_root, *, timeout=1800.0):
        self.calls.append("collect")
        return ToolResult(tool="coverage-run", returncode=0)

    def green_run(self, root, test_path, *, timeout=120.0):
        self.calls.append("green")
        return True, "ok"


def test_collect_coverage_delegates_to_runner(tmp_path):
    fake = _RecordingRunner()
    res = adapters.collect_coverage(tmp_path, tmp_path, tmp_path, runner=fake)
    assert fake.calls == ["collect"] and res.returncode == 0


def test_green_run_delegates_to_runner(tmp_path):
    from pyverdex.skills._testrun import green_run
    fake = _RecordingRunner()
    passed, out = green_run(tmp_path, tmp_path / "t.py", runner=fake)
    assert fake.calls == ["green"] and passed is True and out == "ok"
