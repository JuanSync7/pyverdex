"""Shared test-execution helpers for the apply paths (generate + integrate).

These run an authored test file against the target project — parse it, green-run
it under pytest, and flakiness-check it. No LLM is involved: this is the
deterministic "prove the written test actually works" layer that both the
``generate`` (unit) and ``integrate`` (real-service) apply paths reuse.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from ..config import Thresholds
from ..tools import adapters


def test_path(test_root: Path, subdir: str, module: str, fn: str) -> Path:
    """Deterministic path for a generated test file under ``test_root/subdir``."""
    slug = module.replace(".", "_")
    return test_root / subdir / f"test_{slug}_{fn}.py"


def valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def green_run(root: Path, test_path: Path, timeout: float = 120.0) -> tuple[bool, str]:
    """Run pytest on one test file; return (passed, short_output). rc 0 == green.

    ``root`` (the target project root) is the cwd so the test resolves the
    project's imports and conftest.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q",
             "-p", "no:cacheprovider"],
            cwd=str(root), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "green-run timed out"
    except OSError as exc:  # e.g. cwd gone, interpreter/pytest missing
        return False, f"green-run could not start: {exc}"
    return proc.returncode == 0, (proc.stdout or proc.stderr)[-500:]


def flakiness(root: Path, test_path: Path, thresholds: Thresholds) -> tuple[bool, float | None]:
    """Re-run the written test to catch nondeterminism. Returns (is_flaky, fail_rate).

    A test only counts as flaky when the checker actually completed the minimum
    number of runs AND observed a fail-rate at/above the configured threshold. A
    tool error or too-few runs is treated as *not* flaky (advisory), so a good
    test is never rejected merely because the checker could not run. ``root`` is
    the cwd so the reruns resolve the project's imports (same as the green-run).
    """
    try:
        res = adapters.run_flakiness(
            str(test_path), runs=thresholds.flakiness_min_runs, cwd=root)
    except Exception:  # noqa: BLE001 - flakiness is advisory; never crash the caller
        return False, None
    if not res.ok or res.data is None:
        return False, None
    fail_rate = res.data.get("fail_rate")
    total = res.data.get("total_runs", 0)
    if not isinstance(fail_rate, (int, float)) or total < thresholds.flakiness_min_runs:
        return False, (float(fail_rate) if isinstance(fail_rate, (int, float)) else None)
    return fail_rate >= thresholds.flakiness_max_fail_rate, float(fail_rate)


__all__ = ["test_path", "valid_python", "green_run", "flakiness"]
