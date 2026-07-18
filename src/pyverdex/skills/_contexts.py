"""Per-test coverage contexts + boundary test-attribution (Phase H).

Phase G could only credit a boundary with tests the *engine* wrote; every
hand-written test was invisible to the system dimension. coverage.py **dynamic
contexts** close that gap: with ``[run] dynamic_context = test_function`` on
the audit coverage run (``adapters.collect_coverage(dynamic_contexts=True)``),
the ``.coverage`` DB records *which test executed each line*. This module
reads the attribution back and joins it onto detected boundaries:

- :func:`read_test_contexts` — ``{module: {line: {test labels}}}`` straight
  from ``CoverageData.contexts_by_lineno``; ``None`` when the DB is missing or
  context-free (drives graceful fallback to Phase G behaviour).
- :func:`function_spans` — every function/method's line span(s) via a
  stdlib-ast pass (boundary records only carry a start line, and branch_map
  presence isn't guaranteed).
- :func:`boundary_test_attribution` — boundary span ∩ contexts → the tests
  covering each boundary.
- :func:`test_attribution` — the JSON-serializable orchestrator for
  ``state["test_attribution"]``.

Context-label facts (pinned by the Phase H spike, tests/test_phase_h): a label
is the test module's import name plus the test function —
``tests_pkg.test_api.test_ok`` for package test dirs, ``test_api.test_ok`` for
bare ones — so joins key on the label's *last two segments*. Parametrized
variants collapse into one label; lines executed at import time carry the
empty label ``""`` (excluded here).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Optional

from ._edges import _module_name


def read_test_contexts(
    project_root: Path, source_root: Path,
) -> Optional[dict[str, dict[int, set[str]]]]:
    """``{module: {line: {test labels}}}`` from ``.coverage``; ``None`` when
    the DB is absent, unreadable, empty, or holds no per-test contexts."""
    try:
        import coverage as coverage_lib
    except ImportError:  # pragma: no cover - coverage is a hard dep
        return None
    data_path = Path(project_root) / ".coverage"
    if not data_path.exists():
        return None
    cov = coverage_lib.Coverage(data_file=str(data_path))
    try:
        cov.load()
    except Exception:
        return None
    data = cov.get_data()
    if not data.measured_files():
        return None
    # A context-free DB (toggle off / old run) reports only the "" context —
    # that is "no attribution available", not "no test covered anything".
    if not any(c for c in data.measured_contexts()):
        return None
    src = Path(source_root).resolve()
    result: dict[str, dict[int, set[str]]] = {}
    for fpath in data.measured_files():
        p = Path(fpath)
        try:
            resolved = p.resolve()
            if not resolved.is_relative_to(src):
                continue
        except OSError:
            continue
        by_line: dict[int, set[str]] = {}
        for line, ctxs in data.contexts_by_lineno(fpath).items():
            labelled = {c for c in ctxs if c}  # drop import-time "" context
            if labelled:
                by_line[line] = labelled
        if by_line:
            result[_module_name(resolved, src)] = by_line
    return result or None


def function_spans(source_root: Path) -> dict[tuple[str, str], list[tuple[int, int]]]:
    """``{(module, function_name): [(line_start, line_end), ...]}`` for every
    function *and method* in the source tree.

    Methods key by bare name to match boundary_classifier's ``function_name``;
    a name defined twice in one module keeps *both* spans (attribution then
    unions over them — the same (module, fn) ambiguity Phase G's join already
    has, never a merged interval that would swallow unrelated lines).
    """
    spans: dict[tuple[str, str], list[tuple[int, int]]] = {}
    root = Path(source_root)
    for py in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (SyntaxError, OSError, ValueError):
            continue
        mod = _module_name(py, root)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", None) or node.lineno
                spans.setdefault((mod, node.name), []).append((node.lineno, end))
    return spans


def boundary_test_attribution(
    boundaries: list[dict[str, Any]],
    contexts: dict[str, dict[int, set[str]]],
    spans: dict[tuple[str, str], list[tuple[int, int]]],
) -> dict[tuple[str, str], list[str]]:
    """``{(module, function_name): sorted covering test labels}`` — a test
    covers a boundary when it executed any line inside the boundary's span."""
    out: dict[tuple[str, str], list[str]] = {}
    for b in boundaries:
        key = (str(b.get("module", "")), str(b.get("function_name", "")))
        if key in out:  # boundary listed twice -> one attribution entry
            continue
        tests: set[str] = set()
        mod_lines = contexts.get(key[0], {})
        for start, end in spans.get(key, []):
            for line, ctxs in mod_lines.items():
                if start <= line <= end:
                    tests.update(ctxs)
        out[key] = sorted(tests)
    return out


def test_attribution(
    project_root: Path, source_root: Path,
    boundaries: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    """JSON-serializable payload for ``state["test_attribution"]``.

    Degrades to ``{"have_contexts": False, ...}`` when the ``.coverage`` DB is
    absent or context-free (toggle off, old DB, failed run) — callers fall
    back to Phase G behaviour, never to fake zeros.
    """
    contexts = read_test_contexts(Path(project_root), Path(source_root))
    if contexts is None:
        return {"have_contexts": False, "boundaries": [], "tests_seen": 0}
    all_tests: set[str] = set()
    for by_line in contexts.values():
        for ctxs in by_line.values():
            all_tests.update(ctxs)
    attrib = boundary_test_attribution(
        boundaries or [], contexts, function_spans(Path(source_root)))
    records = [
        {"module": m, "function_name": f, "covering_tests": tests}
        for (m, f), tests in sorted(attrib.items())
    ]
    return {"have_contexts": True, "boundaries": records,
            "tests_seen": len(all_tests)}


__all__ = ["read_test_contexts", "function_spans",
           "boundary_test_attribution", "test_attribution"]
