"""Failure-path coverage for boundary functions (Phase I).

The expensive integration bugs live on the *unhappy* path — the dependency
times out, the connection resets, the write half-commits — yet nothing
measured whether a boundary's error handling was ever exercised. The vendored
``log_contract_validator`` counts logged branches but records no per-branch
line numbers, so this module enumerates handlers itself:

- **Denominator** — boundary functions that HAVE error handling. Handler
  semantics (ADR 0008): one ``ast.ExceptHandler`` clause *body* is one
  handler; multiple excepts on one try are multiple handlers; a nested try
  inside a handler contributes separate handlers (recursive walk);
  ``finally``/``else`` blocks are NOT handlers (cleanup/continuation, not
  recovery); a re-raising handler counts as covered when its lines executed.
  Boundaries with **no** try/except are excluded from the denominator and
  surfaced as the *unprotected boundary* worklist — you can't measure
  recovery that doesn't exist, but you should know it doesn't.
- **Numerator** — a boundary's failure path is *covered* when a named test
  executed one of its handler-body lines (per-test contexts, Phase H); the
  report names *which test forced it*. A handler that only ran at import time
  is not covered. Handler bodies only: the ``except X:`` clause line can
  execute on a type-test without the handler running, so a body written on
  a header line (``except X: return 0``) contributes no measurable line; a
  boundary whose handlers are all like that is reported as not measurable
  (``covered`` None), neither covered nor a measured zero. Without per-test contexts nothing is measured
  (``have_coverage`` False, every ``covered`` None).
- **Scope** — handlers of functions, lambdas and classes *defined inside* the
  boundary belong to those, not to the boundary.

v1 scope: handlers *inside* the boundary function; caller-side handlers
around boundary call sites are deferred (ADR 0008).
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
from typing import Any, Optional

from ._contexts import read_test_contexts
from ._detect import _module_file, own_statement_lines
from ._edges import _executed_lines_by_module

# Cap worklists embedded in state/report (same rationale as _edges._UNCOVERED_CAP)
_SAMPLE_CAP = 50

_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _handler_line_sets(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[set[int]]:
    """One line-set per except-handler *body* within the function (recursive:
    nested trys — including inside handler bodies — contribute their own).
    ``except*`` exception-group handlers (ast.TryStar, PEP 654) count too —
    they'd otherwise silently vanish from the denominator.

    Nested function, lambda and class scopes are not entered: their handlers
    protect them, not this function, and their lines are in no set (a later
    call would light them up). A set holds only the first lines of the body's
    own statements. No header line is ever in a set, so a body on a header
    line yields an empty set — a handler that exists but cannot be measured."""
    handlers: list[set[int]] = []
    pending: deque[ast.AST] = deque(ast.iter_child_nodes(fn))
    while pending:
        node = pending.popleft()
        if isinstance(node, _NESTED_SCOPES):
            continue
        pending.extend(ast.iter_child_nodes(node))
        if not isinstance(node, (ast.Try, ast.TryStar)):
            continue
        for handler in node.handlers:
            # the header may span lines: ``except (\n    ValueError): ...``
            header_end = (getattr(handler.type, "end_lineno", None)
                          if handler.type is not None else None) or handler.lineno
            header = set(range(handler.lineno, header_end + 1))
            handlers.append(own_statement_lines(handler.body) - header)
    return handlers


def boundary_handlers(
    source_root: Path, boundaries: list[dict[str, Any]],
) -> dict[tuple[str, str], list[set[int]]]:
    """``{(module, function_name): [handler line-sets]}`` for each boundary.

    Same-named defs in one module contribute all their handlers (the same
    (module, fn) ambiguity every Phase G/H join has). Unparseable/missing
    modules yield no entry (degrade, never invent).
    """
    out: dict[tuple[str, str], list[set[int]]] = {}
    trees: dict[str, Optional[ast.Module]] = {}
    for b in boundaries:
        module = str(b.get("module", ""))
        fn_name = str(b.get("function_name", ""))
        key = (module, fn_name)
        if key in out:
            continue
        if module not in trees:
            path = _module_file(Path(source_root), module)
            try:
                trees[module] = (ast.parse(path.read_text(encoding="utf-8"))
                                 if path else None)
            except (SyntaxError, OSError, ValueError):
                trees[module] = None
        tree = trees[module]
        if tree is None:
            continue
        handlers: list[set[int]] = []
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == fn_name):
                handlers.extend(_handler_line_sets(node))
        out[key] = handlers
    return out


def failure_path_report(
    project_root: Path, source_root: Path,
    boundaries: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    """JSON-serializable payload for ``state["failure_path_report"]``.

    ``have_coverage`` False (no ``.coverage``, or one without per-test
    contexts) keeps the handler *map* but marks every ``covered`` as None —
    mapped, not measured, never fake zeros.
    """
    bnd_list = boundaries or []
    handlers_by_key = boundary_handlers(Path(source_root), bnd_list)
    executed = _executed_lines_by_module(Path(project_root), Path(source_root))
    contexts = (read_test_contexts(Path(project_root), Path(source_root))
                if executed is not None else None)

    measured = executed is not None and contexts is not None
    protected: list[dict[str, Any]] = []
    unprotected: list[dict[str, str]] = []
    for key, handlers in handlers_by_key.items():
        module, fn_name = key
        if not handlers:
            unprotected.append({"module": module, "function_name": fn_name})
            continue
        record: dict[str, Any] = {
            "module": module, "function_name": fn_name,
            "handlers_total": len(handlers),
        }
        if not measured or contexts is None:
            record.update({"handlers_covered": None, "covered": None,
                           "forcing_tests": []})
        else:
            # a handler counts only when a named test ran one of its lines;
            # lines that ran at import time carry no test
            mod_ctx = contexts.get(module, {})
            covered_handlers = [h for h in handlers
                                if any(mod_ctx.get(line) for line in h)]
            forcing: set[str] = set()
            for h in covered_handlers:
                for line in h:
                    forcing.update(mod_ctx.get(line, set()))
            if any(handlers):
                record.update({
                    "handlers_covered": len(covered_handlers),
                    # any handler exercised => the failure path was hit
                    "covered": bool(covered_handlers),
                    "forcing_tests": sorted(forcing)[:10],
                })
            else:
                # no handler has a line of its own: unknown, not a zero
                record.update({"handlers_covered": None, "covered": None,
                               "forcing_tests": []})
        protected.append(record)

    # `is True`, not truthy: unmeasured records carry covered=None, which must
    # never be confused with a measured False (or sneak into the count)
    covered_n = sum(1 for r in protected if r.get("covered") is True)
    return {
        # True only when "a test forced it" could be measured at all
        "have_coverage": measured,
        "boundaries": protected,
        "unprotected": unprotected[:_SAMPLE_CAP],
        "unprotected_total": len(unprotected),
        "total": len(protected),
        "covered": covered_n if measured else None,
    }


__all__ = ["boundary_handlers", "failure_path_report"]
