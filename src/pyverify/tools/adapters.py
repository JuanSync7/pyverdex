"""Typed adapters over the vendored deterministic tools.

Each adapter shells out to one vendored tool via ``python -m
pyverify.tools.vendored.<tool>.<tool>`` (so the tools' relative imports keep
working), parses its JSON stdout, and returns a :class:`ToolResult`. These
adapters are the *deterministic nodes* of the LangGraph engine — no LLM is
involved in measurement.

Exit-code convention inherited from the tools: ``0`` = pass/clean,
``1`` = findings/fail, ``2`` = tool error. ``coverage_analyzer`` uses
``0`` = complete, ``2`` = error.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

_VENDORED = "pyverify.tools.vendored"


class ToolResult(BaseModel):
    """Normalised result of one deterministic tool invocation."""

    tool: str
    returncode: int
    data: Optional[dict[str, Any]] = None
    stdout: str = ""
    stderr: str = ""
    parse_error: Optional[str] = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """True when the tool ran successfully (rc != 2 and not timed out)."""
        return not self.timed_out and self.returncode != 2

    @property
    def has_findings(self) -> bool:
        return self.returncode == 1


def _run_module(
    module: str,
    args: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout: float = 600.0,
) -> ToolResult:
    cmd = [sys.executable, "-m", f"{_VENDORED}.{module}", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return ToolResult(
            tool=module,
            returncode=124,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=f"timed out after {timeout}s",
            timed_out=True,
        )

    data: Optional[dict[str, Any]] = None
    parse_error: Optional[str] = None
    out = proc.stdout.strip()
    if out:
        try:
            parsed = json.loads(out)
            data = parsed if isinstance(parsed, dict) else {"items": parsed}
        except json.JSONDecodeError as exc:
            parse_error = f"non-JSON stdout: {exc}"

    return ToolResult(
        tool=module,
        returncode=proc.returncode,
        data=data,
        stdout=proc.stdout,
        stderr=proc.stderr,
        parse_error=parse_error,
    )


# ---------------------------------------------------------------------------
# Static analysis / lint
# ---------------------------------------------------------------------------


def run_lint(
    source_root: Path,
    *,
    tools: Optional[str] = None,
    exclude: Optional[list[str]] = None,
    timeout: float = 900.0,
) -> ToolResult:
    args = [str(source_root)]
    if tools:
        args += ["--tools", tools]
    for pat in exclude or []:
        args += ["--exclude", pat]
    return _run_module("lint_reporter.lint_reporter", args, timeout=timeout)


def run_secret_scan(file_path: Path, *, timeout: float = 120.0) -> ToolResult:
    return _run_module(
        "secret_scanner.secret_scanner",
        [str(file_path), "--format", "json"],
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Coverage: line gaps (needs a .coverage file in `cwd`) and static edges
# ---------------------------------------------------------------------------


def collect_coverage(
    project_root: Path,
    source_root: Path,
    test_root: Path,
    *,
    timeout: float = 1800.0,
) -> ToolResult:
    """Run the target test suite under coverage.py to produce a ``.coverage``
    file in ``project_root`` (consumed by :func:`run_coverage_gaps`)."""
    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--source={source_root}",
        "-m",
        "pytest",
        str(test_root),
        "-q",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool="coverage-run", returncode=124, timed_out=True,
                          stderr=f"coverage run timed out after {timeout}s")
    # pytest rc: 0 pass, 1 tests failed, 5 no tests collected — all leave a
    # usable .coverage file, so treat anything but a hard error as runnable.
    return ToolResult(
        tool="coverage-run",
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def run_coverage_gaps(
    project_root: Path,
    source_root: Path,
    *,
    timeout: float = 600.0,
) -> ToolResult:
    """Per-function line-coverage gaps. Reads ``.coverage`` from project_root."""
    return _run_module(
        "coverage_analyzer.coverage_analyzer",
        [str(source_root)],
        cwd=project_root,
        timeout=timeout,
    )


def run_edges(
    source_root: Path,
    *,
    test_path: str = "tests/",
    baseline: Optional[Path] = None,
    sha: Optional[str] = None,
    timeout: float = 600.0,
) -> ToolResult:
    """Cross-package call-graph edges (function-to-function coverage), static."""
    args = [str(source_root), "--edges", "--test-path", test_path]
    if baseline:
        args += ["--baseline", str(baseline)]
    if sha:
        args += ["--sha", sha]
    return _run_module("coverage_analyzer.coverage_analyzer", args, timeout=timeout)


# ---------------------------------------------------------------------------
# Branch / boundary / log structure (static AST)
# ---------------------------------------------------------------------------


def run_branch_map(
    source_root: Path,
    *,
    module: Optional[str] = None,
    function: Optional[str] = None,
    include_private: bool = False,
    timeout: float = 600.0,
) -> ToolResult:
    args = [str(source_root)]
    if module:
        args += ["--module", module]
    if function:
        args += ["--function", function]
    if include_private:
        args.append("--include-private")
    return _run_module("branch_mapper.branch_mapper", args, timeout=timeout)


def run_boundary(
    source_root: Path,
    *,
    include_internals: bool = False,
    timeout: float = 600.0,
) -> ToolResult:
    args = [str(source_root)]
    if include_internals:
        args.append("--include-internals")
    return _run_module("boundary_classifier.boundary_classifier", args, timeout=timeout)


def run_log_contract(
    source_root: Path,
    *,
    policy: Optional[Path] = None,
    ignore_patterns: Optional[str] = None,
    timeout: float = 600.0,
) -> ToolResult:
    args = [str(source_root)]
    if policy:
        args += ["--policy", str(policy)]
    if ignore_patterns:
        args += ["--ignore-patterns", ignore_patterns]
    return _run_module(
        "log_contract_validator.log_contract_validator", args, timeout=timeout
    )


# ---------------------------------------------------------------------------
# Test-effectiveness: assertion quality, mutation, flakiness, hypothesis
# ---------------------------------------------------------------------------


def run_assertion_quality(
    test_root: Path,
    *,
    threshold: float = 0.5,
    min_assertions: int = 2,
    timeout: float = 600.0,
) -> ToolResult:
    return _run_module(
        "assertion_quality.assertion_quality",
        [str(test_root), "--threshold", str(threshold),
         "--min-assertions", str(min_assertions)],
        timeout=timeout,
    )


def run_mutation(
    module_path: Path,
    *,
    function: Optional[str] = None,
    test_cmd: str = "pytest",
    max_lines: int = 20,
    timeout_per_mutant: float = 30.0,
    timeout: float = 1800.0,
    cwd: Optional[Path] = None,
) -> ToolResult:
    args = [str(module_path), "--test-cmd", test_cmd,
            "--max-lines", str(max_lines), "--timeout", str(timeout_per_mutant)]
    if function:
        args += ["--function", function]
    return _run_module("mutation_runner.mutation_runner", args, cwd=cwd, timeout=timeout)


def run_flakiness(
    test_node_id: str,
    *,
    runs: int = 10,
    timeout_per_run: float = 120.0,
    timeout: float = 3600.0,
) -> ToolResult:
    return _run_module(
        "flakiness_checker.flakiness_checker",
        [test_node_id, "--runs", str(runs), "--timeout", str(timeout_per_run)],
        timeout=timeout,
    )


def run_hypothesis_strategies(
    source_root: Path,
    *,
    module: Optional[str] = None,
    function: Optional[str] = None,
    public_only: bool = False,
    timeout: float = 600.0,
) -> ToolResult:
    args = [str(source_root)]
    if module:
        args += ["--module", module]
    if function:
        args += ["--function", function]
    if public_only:
        args.append("--public-only")
    return _run_module(
        "hypothesis_strategy_generator.hypothesis_strategy_generator",
        args,
        timeout=timeout,
    )


__all__ = [
    "ToolResult",
    "run_lint",
    "run_secret_scan",
    "collect_coverage",
    "run_coverage_gaps",
    "run_edges",
    "run_branch_map",
    "run_boundary",
    "run_log_contract",
    "run_assertion_quality",
    "run_mutation",
    "run_flakiness",
    "run_hypothesis_strategies",
]
