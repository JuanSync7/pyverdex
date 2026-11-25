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
- a factory that cannot be judged by line (see ``_lines``: no line only it
  can emit, or its entry line is shared), or whose module the target leaves
  out of measurement → that one record has ``executed=None``: unknown,
  neither executed nor a measured zero;
- no factories detected → the dimension is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._contexts import measured_modules, read_test_contexts
from ._detect import detect_app_factories
from ._edges import _executed_lines_by_module
from ._lines import Anchors, judge


def boot_report(project_root: Path, source_root: Path) -> dict[str, Any]:
    """JSON-serializable payload for ``state["boot_report"]``."""
    factories = detect_app_factories(Path(source_root))
    executed = _executed_lines_by_module(Path(project_root), Path(source_root))
    contexts = (read_test_contexts(Path(project_root), Path(source_root))
                if executed is not None else None)

    in_data = (measured_modules(Path(project_root), Path(source_root))
               if contexts is not None else None)
    measured = (executed is not None and contexts is not None
                and in_data is not None)
    records: list[dict[str, Any]] = []
    executed_n = 0
    for f in factories:
        record = dict(f)
        if (not measured or contexts is None or in_data is None
                or f["module"] not in in_data):
            # no per-test data at all, or the target leaves this module out
            # of measurement: unknown
            record.update({"executed": None, "tests": []})
        else:
            anchors = Anchors(frozenset(f.get("body_lines", [])),
                              f.get("entry_line"))
            ran, tests = judge(anchors, contexts.get(f["module"], {}))
            record.update({"executed": ran, "tests": tests[:10]})
            if ran:
                executed_n += 1
        records.append(record)

    return {
        # True only when "ran under a test" could be measured at all
        "have_coverage": measured,
        "factories": records,
        "total": len(records),
        "unmeasurable": (sum(1 for r in records if r["executed"] is None)
                         if measured else None),
        "executed": executed_n if measured else None,
    }


__all__ = ["boot_report"]
