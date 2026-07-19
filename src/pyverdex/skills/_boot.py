"""Boot smoke — is the composition root ever *constructed* by a test? (Phase I)

Import-smoke proves every module imports; it does not prove the app can be
ASSEMBLED: the factory that binds settings, resolves the DI container and
instantiates every registered dependency can still be broken while all its
parts import cleanly. This module joins :func:`_detect.detect_app_factories`
(conventional factory names, or a body that constructs a framework app) with
the executed-lines data the audit coverage run already produced: a factory is
*executed* when any line of its body ran under some test; with Phase H
contexts the report names which test.

Degrades honestly: no ``.coverage`` → factories are *mapped* with
``executed=None`` (measured-nothing, never fake zeros); no factories detected
→ the dimension is absent entirely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._contexts import read_test_contexts
from ._detect import detect_app_factories
from ._edges import _executed_lines_by_module


def boot_report(project_root: Path, source_root: Path) -> dict[str, Any]:
    """JSON-serializable payload for ``state["boot_report"]``."""
    factories = detect_app_factories(Path(source_root))
    executed = _executed_lines_by_module(Path(project_root), Path(source_root))
    contexts = (read_test_contexts(Path(project_root), Path(source_root))
                if executed is not None else None)

    records: list[dict[str, Any]] = []
    executed_n = 0
    for f in factories:
        record = dict(f)
        if executed is None:
            record.update({"executed": None, "tests": []})
        else:
            hit = executed.get(f["module"], set())
            # body lines only: the def line executes at import time, which
            # would mark every merely-imported factory as "executed"
            span = set(range(f.get("body_start", f["line_start"]),
                             f["line_end"] + 1))
            ran = bool(span & hit)
            tests: set[str] = set()
            if ran and contexts:
                mod_ctx = contexts.get(f["module"], {})
                for line in span:
                    tests.update(mod_ctx.get(line, set()))
            record.update({"executed": ran, "tests": sorted(tests)[:10]})
            if ran:
                executed_n += 1
        records.append(record)

    return {
        "have_coverage": executed is not None,
        "factories": records,
        "total": len(records),
        "executed": executed_n if executed is not None else None,
    }


__all__ = ["boot_report"]
