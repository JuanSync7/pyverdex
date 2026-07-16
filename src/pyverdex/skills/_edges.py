"""Function-to-function call-edge coverage (Phase F).

The vendored ``coverage_analyzer --edges`` only maps *cross-package, module-to-
module* edges — it cannot answer "which function calls which, and is that call
exercised". This module fills that gap with a stdlib-``ast`` extractor at
*function* granularity plus a **call-site-covered** numerator:

- **Denominator** — every statically-resolvable internal call edge
  ``(caller_module, caller_function) -> (callee_module, callee_function)`` where
  the callee is a *top-level function defined in the source tree*. External /
  dynamic / method calls that don't resolve to an internal function are not part
  of the denominator (we don't count what we can't measure).
- **Numerator** — an edge is *exercised* when any of its call-site lines executed,
  read straight from the coverage.py ``.coverage`` data. This reuses the line
  data we already collect (no runtime call tracing); a covered call site whose
  branch was never taken is a known slight over-count, documented in ADR 0004.

Everything here is pure stdlib except the optional ``coverage`` read, which
degrades gracefully (``pct=None``) when no ``.coverage`` file is present.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

# Cap the "what to test next" worklist embedded in state/report so a large
# codebase can't bloat the JSON; the full total is always reported alongside.
_UNCOVERED_CAP = 50


def _module_name(path: Path, source_root: Path) -> str:
    """Dotted module name for a file, with ``__init__`` collapsed to its package
    so it matches how ``from pkg import foo`` resolves."""
    rel = path.relative_to(source_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _build_import_map(tree: ast.Module, caller_module: str,
                      is_init: bool = False) -> dict[str, str]:
    """{local_name: dotted_target} for every import (absolute + relative).

    Follows Python binding semantics: ``import a.b.c`` binds the top-level name
    ``a`` (to package ``a``), while ``import a.b.c as x`` binds ``x`` to
    ``a.b.c``. Relative imports resolve against the caller's package; when the
    caller is a package ``__init__`` (already collapsed to the package name),
    ``level=1`` means *the package itself*, so one fewer component is stripped.
    """
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    mapping[alias.asname] = alias.name
                else:  # `import a.b.c` binds `a`, not `a.b.c`
                    top = alias.name.split(".")[0]
                    mapping[top] = top
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level and node.level > 0:  # relative: resolve vs caller pkg
                parts = caller_module.split(".")
                strip = node.level - (1 if is_init else 0)
                base_parts = parts[: max(0, len(parts) - strip)]
                base = ".".join(base_parts) + ("." + base if base else "")
            for alias in node.names:
                local = alias.asname or alias.name
                mapping[local] = base + "." + alias.name if base else alias.name
    return mapping


class _CallVisitor(ast.NodeVisitor):
    """Collect internal function->function edges, keyed by call site line."""

    def __init__(self, caller_module: str, import_map: dict[str, str],
                 known: set[tuple[str, str]], known_modules: set[str]) -> None:
        self.caller_module = caller_module
        self.import_map = import_map
        self.known = known  # {(module, top_level_function)}
        self.known_modules = known_modules  # dotted names of source modules
        self.stack: list[str] = []  # enclosing class/function qualname parts
        self.edges: dict[tuple[str, str, str, str], set[int]] = {}

    def _enter(self, name: str, node: ast.AST) -> None:
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._enter(node.name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._enter(node.name, node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _caller(self) -> str:
        return ".".join(self.stack) if self.stack else "<module>"

    def _resolve(self, func: ast.expr) -> Optional[tuple[str, str]]:
        # bare name: from-imported function, or a function in this same module
        if isinstance(func, ast.Name):
            target = self.import_map.get(func.id)
            # skip when the name is itself a source module (`from a import submod`)
            # so a `submod()` call can't collide with a same-named function in `a`
            if target and target not in self.known_modules:
                mod, _, fn = target.rpartition(".")
                if (mod, fn) in self.known:
                    return (mod, fn)
            if (self.caller_module, func.id) in self.known:
                return (self.caller_module, func.id)
        # attribute on an imported module alias: `mod.func()`
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base = self.import_map.get(func.value.id)
            if base and (base, func.attr) in self.known:
                return (base, func.attr)
        return None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        callee = self._resolve(node.func)
        if callee is not None:
            key = (self.caller_module, self._caller(), callee[0], callee[1])
            self.edges.setdefault(key, set()).add(node.lineno)
        self.generic_visit(node)


def build_function_edges(source_root: Path) -> list[dict]:
    """Static function->function call edges to internal top-level functions.

    Two passes: gather every module's top-level function set (the resolvable
    callee universe), then walk each module resolving calls against it. Returns
    a sorted, de-duplicated edge list; each edge carries its ``call_sites``.
    """
    source_root = Path(source_root)
    parsed: dict[str, tuple[ast.Module, dict[str, str]]] = {}
    known: set[tuple[str, str]] = set()

    for py in sorted(source_root.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (SyntaxError, OSError, ValueError):
            continue
        mod = _module_name(py, source_root)
        parsed[mod] = (tree, _build_import_map(tree, mod, py.name == "__init__.py"))
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                known.add((mod, n.name))

    known_modules = set(parsed)
    edges: list[dict] = []
    for mod, (tree, imap) in parsed.items():
        v = _CallVisitor(mod, imap, known, known_modules)
        v.visit(tree)
        for (cm, cf, em, ef), lines in v.edges.items():
            edges.append({
                "caller_module": cm, "caller_function": cf,
                "callee_module": em, "callee_function": ef,
                "call_sites": sorted(lines),
            })
    edges.sort(key=lambda e: (e["caller_module"], e["caller_function"],
                              e["callee_module"], e["callee_function"]))
    return edges


def compute_edge_coverage(edges: list[dict],
                          executed_by_module: dict[str, set[int]]) -> dict:
    """Pure numerator: an edge is exercised iff any call site executed."""
    exercised = 0
    uncovered: list[dict] = []
    for e in edges:
        hit_lines = executed_by_module.get(e["caller_module"], set())
        if any(ln in hit_lines for ln in e["call_sites"]):
            exercised += 1
        else:
            uncovered.append(e)
    total = len(edges)
    pct = round(exercised / total * 100.0, 2) if total else 100.0
    return {
        "total": total,
        "exercised": exercised,
        "pct": pct,
        "uncovered_total": len(uncovered),
        "uncovered": uncovered[:_UNCOVERED_CAP],
        "have_coverage": True,
    }


def _executed_lines_by_module(project_root: Path,
                              source_root: Path) -> Optional[dict[str, set[int]]]:
    """{module: {executed line numbers}} from ``.coverage``; None if unavailable."""
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
    # .load() succeeds silently on an empty/absent file in modern coverage.py, so
    # gate on whether any file was actually measured before trusting the numerator.
    if not cov.get_data().measured_files():
        return None
    result: dict[str, set[int]] = {}
    any_data = False
    for py in sorted(Path(source_root).rglob("*.py")):
        try:
            _, statements, _, missing, _ = cov.analysis2(str(py))
        except Exception:
            continue
        result[_module_name(py, Path(source_root))] = set(statements) - set(missing)
        any_data = True
    return result if any_data else None


def edge_coverage(project_root: Path, source_root: Path) -> dict:
    """Function-edge coverage for a project. JSON-serializable; degrades to
    ``exercised=None, pct=None`` (just the mapped total) with no coverage data."""
    edges = build_function_edges(Path(source_root))
    executed = _executed_lines_by_module(Path(project_root), Path(source_root))
    if executed is None:
        return {"total": len(edges), "exercised": None, "pct": None,
                "uncovered_total": len(edges),
                "uncovered": edges[:_UNCOVERED_CAP], "have_coverage": False}
    return compute_edge_coverage(edges, executed)


__all__ = ["build_function_edges", "compute_edge_coverage", "edge_coverage"]
