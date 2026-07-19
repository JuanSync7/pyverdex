"""Static test-realness classifier (Phase H2).

Phase H1 made the system dimension count every test that exercises a boundary;
this module answers the follow-up question the report couldn't: *what kind of
test was it?* A boundary "covered" only by tests that replace its dependency
with a mock is verified against an assumption, not against the dependency —
the classic place integration bugs survive.

Each ``test_*`` function is tiered by the **dependency-replacing** signals it
uses (directly, via decorators, or via the pytest fixtures it requests):

- ``mock`` — the dependency is a programmed double: unittest.mock / patch,
  pytest-mock's ``mocker``, ``monkeypatch``, responses/respx/requests-mock,
  vcr cassettes.
- ``fake`` — a working substitute engine: moto, fakeredis, mongomock, pyfakefs.
- ``in_process`` — the real app driven in-process: fastapi/starlette
  ``TestClient``, django/flask test clients, httpx ``ASGITransport``.
- ``real`` — real infrastructure: testcontainers, docker fixtures.

**Control signals are neutral and never demote** (the review-hardened rule): a
test using freezegun/time-machine, seeded randomness, ``tmp_path`` or
``caplog`` while hitting a real database is a *real* test — time/input control
is not dependency replacement.

A test's tier is the **lowest** rung among its dependency-replacing signals
(mock < fake < in_process < real); a test with none is ``unknown`` — meaning
whatever dependencies it touched ran *unreplaced* (the report grades that as
real-equivalent: demotion needs positive evidence, see ADR 0007).

Fixture resolution follows pytest semantics statically: fixtures defined in
the test module itself win, then conftest.py files from the test file's
directory up to the project root (nearest wins); fixture→fixture dependencies
resolve transitively (cycle-guarded, depth-capped); ``autouse`` fixtures apply
to every test in their scope directory; plugin-provided fixtures come from a
declarative registry. Unresolvable fixtures contribute nothing (never a
crash, never a demotion).

``test_id`` is ``<file-stem>.<function>`` — the same last-two-segments key the
builder uses to join coverage context labels (ADR 0006).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterator, Optional

TIER_RANK = {"mock": 0, "fake": 1, "in_process": 2, "real": 3}

# Dependency-replacing libraries, keyed by their import roots. Anything not
# listed here (freezegun, hypothesis, numpy, ...) is a NEUTRAL control signal.
_LIB_TIERS: dict[str, str] = {
    "unittest.mock": "mock", "mock": "mock", "pytest_mock": "mock",
    "responses": "mock", "respx": "mock", "requests_mock": "mock",
    "aioresponses": "mock", "httpretty": "mock", "vcr": "mock",
    "moto": "fake", "fakeredis": "fake", "mongomock": "fake", "pyfakefs": "fake",
    "fastapi.testclient": "in_process", "starlette.testclient": "in_process",
    "django.test": "in_process", "flask.testing": "in_process",
    "testcontainers": "real", "docker": "real",
}

# Names that signal dependency replacement when referenced in a test body even
# without a classifying import (e.g. `httpx.ASGITransport(app=...)`).
_NAME_TIERS: dict[str, str] = {
    "TestClient": "in_process",
    "ASGITransport": "in_process",
}

# Plugin-provided fixtures (not resolvable from conftest ASTs). Neutral
# fixtures are listed explicitly so a future maintainer sees the decision.
_PLUGIN_FIXTURES: dict[str, Optional[str]] = {
    "mocker": "mock", "monkeypatch": "mock",
    "responses": "mock", "requests_mock": "mock", "httpx_mock": "mock",
    "tmp_path": None, "tmp_path_factory": None, "tmpdir": None,
    "caplog": None, "capsys": None, "capfd": None, "capfdbinary": None,
    "freezer": None, "time_machine": None, "recwarn": None, "request": None,
}

_MAX_FIXTURE_DEPTH = 8


def _lib_tier(dotted: str) -> Optional[str]:
    """Tier for an imported module path, longest-prefix match."""
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        tier = _LIB_TIERS.get(".".join(parts[:i]))
        if tier:
            return tier
    return None


class _Module:
    """One parsed test/conftest module: its tiered names and fixture defs."""

    def __init__(self, path: Path, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        # local name -> tier, for names bound by imports of tiered libraries
        self.name_tiers: dict[str, str] = {}
        # fixture name -> (def node, autouse)
        self.fixtures: dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]] = {}
        self._index()

    def _index(self) -> None:
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    tier = _lib_tier(alias.name)
                    if tier:
                        local = alias.asname or alias.name.split(".")[0]
                        self.name_tiers[local] = tier
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    tier = _lib_tier(f"{base}.{alias.name}") or _lib_tier(base)
                    if tier:
                        self.name_tiers[alias.asname or alias.name] = tier
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fix = _fixture_decorator(node)
                if fix is not None:
                    self.fixtures[node.name] = (node, fix)


def _fixture_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[bool]:
    """None if not a fixture; else its ``autouse`` flag.

    Recognises ``@pytest.fixture``, ``@fixture`` and the called forms.
    """
    for dec in node.decorator_list:
        call = dec if isinstance(dec, ast.Call) else None
        target = call.func if call else dec
        name = target.attr if isinstance(target, ast.Attribute) else (
            target.id if isinstance(target, ast.Name) else None)
        if name == "fixture":
            autouse = False
            if call:
                for kw in call.keywords:
                    if kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                        autouse = bool(kw.value.value)
            return autouse
    return None


def _used_names(node: ast.AST) -> Iterator[str]:
    """Every Name referenced in ``node`` (incl. attribute roots)."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            yield n.id


def _body_signals(fn: ast.FunctionDef | ast.AsyncFunctionDef,
                  module: _Module) -> list[tuple[str, str]]:
    """(signal, tier) pairs from a function's decorators + body: tiered
    imported names actually referenced, plus bare tiered class names."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in _used_names(fn):
        if name in seen:
            continue
        seen.add(name)
        tier = module.name_tiers.get(name)
        if tier:
            out.append((f"use:{name}", tier))
        elif name in _NAME_TIERS:
            out.append((f"use:{name}", _NAME_TIERS[name]))
    return out


def _param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = fn.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    return [n for n in names if n not in ("self", "cls")]


class _Classifier:
    """Classify every test function under a test root."""

    def __init__(self, test_root: Path, project_root: Path) -> None:
        self.test_root = Path(test_root)
        self.project_root = Path(project_root)
        self._modules: dict[Path, Optional[_Module]] = {}
        # dependency-replacing signals contributed by autouse fixtures — a
        # suite-level caveat, not per-test tier evidence (see classify_file)
        self.autouse_replacements: set[str] = set()

    def _module(self, path: Path) -> Optional[_Module]:
        if path not in self._modules:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                self._modules[path] = _Module(path, tree)
            except (SyntaxError, OSError, ValueError):
                self._modules[path] = None
        return self._modules[path]

    def _conftest_chain(self, test_file: Path) -> list[_Module]:
        """conftest modules from the test file's directory up to project_root,
        nearest first (pytest lookup order)."""
        chain: list[_Module] = []
        directory = test_file.parent
        while True:
            conftest = directory / "conftest.py"
            if conftest.exists():
                mod = self._module(conftest)
                if mod:
                    chain.append(mod)
            if directory == self.project_root or directory == directory.parent:
                break
            directory = directory.parent
        return chain

    def _fixture_signals(self, name: str, scope: list[_Module],
                         stack: frozenset[str], depth: int) -> list[tuple[str, str]]:
        """Signals contributed by requesting fixture ``name`` (transitive)."""
        if depth > _MAX_FIXTURE_DEPTH or name in stack:
            return []
        if name in _PLUGIN_FIXTURES:
            tier = _PLUGIN_FIXTURES[name]
            return [(f"fixture:{name}", tier)] if tier else []
        for mod in scope:  # local module first, then nearest conftest wins
            entry = mod.fixtures.get(name)
            if entry is None:
                continue
            node, _autouse = entry
            out = _body_signals(node, mod)
            out = [(f"fixture:{name}->{sig}", tier) for sig, tier in out]
            for dep in _param_names(node):
                out.extend(self._fixture_signals(
                    dep, scope, stack | {name}, depth + 1))
            return out
        return []  # unresolvable (plugin we don't know, dynamic) -> no signal

    def classify_file(self, test_file: Path) -> list[dict[str, Any]]:
        mod = self._module(test_file)
        if mod is None:
            return []
        scope = [mod, *self._conftest_chain(test_file)]
        # Autouse fixtures apply to every test in scope — but they are SUITE
        # POLICY, not the test author's verification choice. Dogfood evidence:
        # one autouse harness stub (monkeypatching an internal helper for
        # speed) demoted 162/162 of this repo's own tests to mock — a
        # classifier with zero discrimination. So autouse replacement signals
        # are RECORDED (and rolled up as a suite caveat) but never set a
        # test's tier; only signals the test itself uses or requests do.
        autouse_signals: list[tuple[str, str]] = []
        for m in scope:
            for fname, (_node, autouse) in m.fixtures.items():
                if autouse:
                    autouse_signals.extend(
                        (f"autouse:{sig}", tier)
                        for sig, tier in self._fixture_signals(
                            fname, scope, frozenset(), 0))
        self.autouse_replacements.update(s for s, _t in autouse_signals)
        records: list[dict[str, Any]] = []
        for node in ast.walk(mod.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test"):
                continue
            if _fixture_decorator(node) is not None:  # a fixture, not a test
                continue
            signals = _body_signals(node, mod)
            for param in _param_names(node):
                signals.extend(self._fixture_signals(param, scope, frozenset(), 0))
            # lowest rung among dependency-replacing signals; none -> unknown
            tier = "unknown"
            best = None
            for _sig, t in signals:
                rank = TIER_RANK[t]
                if best is None or rank < best:
                    best, tier = rank, t
            records.append({
                "test_id": f"{test_file.stem}.{node.name}",
                "file": str(test_file),
                "line": node.lineno,
                "tier": tier,
                "signals": sorted({s for s, _t in signals}
                                  | {s for s, _t in autouse_signals}),
            })
        return records


def _iter_test_files(test_root: Path) -> Iterator[Path]:
    for py in sorted(test_root.rglob("*.py")):
        if py.name.startswith("test_") or py.name.endswith("_test.py"):
            yield py


def classify_tests(test_root: Path, project_root: Path) -> dict[str, Any]:
    """JSON-serializable payload for ``state["realness_report"]``."""
    clf = _Classifier(Path(test_root), Path(project_root))
    tests: list[dict[str, Any]] = []
    for test_file in _iter_test_files(Path(test_root)):
        tests.extend(clf.classify_file(test_file))
    counts: dict[str, int] = {}
    for t in tests:
        counts[t["tier"]] = counts.get(t["tier"], 0) + 1
    return {"have_report": True, "tests": tests, "counts": counts,
            # ambient replacement the suite applies to EVERY test (autouse) —
            # surfaced so "real" grades are read with this caveat in mind
            "autouse_replacements": sorted(clf.autouse_replacements)}


__all__ = ["classify_tests", "TIER_RANK"]
