"""Boot smoke — is the composition root ever *constructed* by a test? (Phase I)

Import-smoke proves every module imports; it does not prove the app can be
ASSEMBLED: the factory that binds settings, resolves the DI container and
instantiates every registered dependency can still be broken while all its
parts import cleanly. This module joins :func:`_detect.detect_app_factories`
(conventional factory names, or a body that constructs a framework app) with
the per-test contexts the audit coverage run recorded: a factory is
*executed* only when a body line ran **under a named test**. A line that ran
at import time (a module-level ``app = create_app()``) carries no test and
does not count.

Degrades honestly, never to fake zeros:

- no ``.coverage``, or one without per-test contexts → "under a test" cannot
  be told from "at import", so factories are *mapped* with ``executed=None``
  and ``have_coverage`` is False;
- a factory whose body shares the ``def`` line (``def create_app(): ...``)
  cannot be measured by line → that one record has ``executed=None`` and is
  not counted as executed;
- no factories detected → the dimension is absent.
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

    measured = executed is not None and contexts is not None
    records: list[dict[str, Any]] = []
    executed_n = 0
    for f in factories:
        record = dict(f)
        # body lines only, and never the def line: it executes at import
        # time, which would mark every merely-imported factory as "executed"
        span = set(range(f.get("body_start", f["line_start"]),
                         f["line_end"] + 1)) - {f["line_start"]}
        if not measured or contexts is None or not span:
            record.update({"executed": None, "tests": []})
        else:
            mod_ctx = contexts.get(f["module"], {})
            tests: set[str] = set()
            for line in span:
                tests.update(mod_ctx.get(line, set()))
            ran = bool(tests)
            record.update({"executed": ran, "tests": sorted(tests)[:10]})
            if ran:
                executed_n += 1
        records.append(record)

    return {
        # True only when "ran under a test" could be measured at all
        "have_coverage": measured,
        "factories": records,
        "total": len(records),
        "executed": executed_n if measured else None,
    }


__all__ = ["boot_report"]
