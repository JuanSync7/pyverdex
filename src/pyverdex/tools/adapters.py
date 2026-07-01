"""Typed adapters over the vendored deterministic tools.

Each adapter shells out to one vendored tool via ``python -m
pyverdex.tools.vendored.<tool>.<tool>`` (so the tools' relative imports keep
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
from typing import Any, Optional, Protocol

from pydantic import BaseModel

_VENDORED = "pyverdex.tools.vendored"


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
# Test runner seam: abstract "run the project's tests" so the hardcoded
# coverage.py + pytest path becomes one implementation. PytestRunner is the only
# concrete runner today; the Protocol is the extension point for unittest and,
# later, non-Python runners (groundwork only — see ADR 0003).
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """A test runner. Exit-code convention: a run that *completes* yields a
    ToolResult with ``ok`` True even when tests fail (rc=1); rc=2/timeout means
    the runner itself could not run."""

    name: str

    def collect_coverage(self, project_root: Path, source_root: Path,
                         test_root: Path, *, timeout: float = 1800.0) -> "ToolResult":
        """Run the suite under coverage to leave a ``.coverage`` file in
        ``project_root``."""
        ...

    def green_run(self, root: Path, test_path: Path, *,
                  timeout: float = 120.0) -> tuple[bool, str]:
        """Run one test file; return ``(passed, short_output)``."""
        ...


class PytestRunner:
    """Default Runner: coverage.py + pytest (the historical hardcoded path)."""

    name = "pytest"

    def collect_coverage(self, project_root: Path, source_root: Path,
                         test_root: Path, *, timeout: float = 1800.0) -> "ToolResult":
        cmd = [
            sys.executable, "-m", "coverage", "run",
            "--branch",  # record arc data so coverage_totals() can report branch %
            f"--source={source_root}", "-m", "pytest", str(test_root), "-q",
        ]
        try:
            proc = subprocess.run(cmd, cwd=str(project_root), capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return ToolResult(tool="coverage-run", returncode=124, timed_out=True,
                              stderr=f"coverage run timed out after {timeout}s")
        # pytest rc: 0 pass, 1 tests failed, 5 no tests collected — all leave a
        # usable .coverage file, so treat anything but a hard error as runnable.
        return ToolResult(tool="coverage-run", returncode=proc.returncode,
                          stdout=proc.stdout, stderr=proc.stderr)

    def green_run(self, root: Path, test_path: Path, *,
                  timeout: float = 120.0) -> tuple[bool, str]:
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


_RUNNERS: dict[str, Runner] = {"pytest": PytestRunner()}


def get_runner(name: str = "pytest") -> Runner:
    """Return the registered Runner for ``name`` (only ``pytest`` today)."""
    try:
        return _RUNNERS[name]
    except KeyError:
        raise ValueError(
            f"unknown runner '{name}'; known: {sorted(_RUNNERS)}") from None


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
    runner: Optional[Runner] = None,
) -> ToolResult:
    """Run the target test suite under coverage.py to produce a ``.coverage``
    file in ``project_root`` (consumed by :func:`run_coverage_gaps`).

    Delegates to the selected :class:`Runner` (pytest by default), which is the
    seam for alternate runners.
    """
    return (runner or get_runner()).collect_coverage(
        project_root, source_root, test_root, timeout=timeout)


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


def coverage_totals(project_root: Path, source_root: Path) -> ToolResult:
    """Whole-codebase line (and branch) coverage from the ``.coverage`` file.

    Unlike :func:`run_coverage_gaps` — which lists only the *gap* functions via
    the vendored analyzer — this sums coverage.py's per-file numbers across every
    ``*.py`` under ``source_root`` (including files that were never imported, so
    they count as 0%). The result is the honest, whole-codebase denominator:
    ``covered / executable`` lines, and ``covered / total`` branches when the
    ``.coverage`` data carries arcs (see ``--branch`` in :func:`collect_coverage`).

    Computed directly via the ``coverage`` library — no vendored tool, no
    subprocess — and degrades gracefully (returns rc=2) when coverage data or the
    private numbers API is unavailable.
    """
    try:
        import coverage as coverage_lib
    except ImportError as exc:  # pragma: no cover - coverage is a hard dep
        return ToolResult(tool="coverage-totals", returncode=2,
                          stderr=f"coverage library unavailable: {exc}")

    cov = coverage_lib.Coverage(data_file=str(Path(project_root) / ".coverage"))
    try:
        cov.load()
    except Exception as exc:  # NoDataError and friends
        return ToolResult(tool="coverage-totals", returncode=2,
                          stderr=f"no coverage data: {exc}")

    exec_lines = miss_lines = 0
    tot_branches = miss_branches = 0
    have_branch = False
    files = 0
    for py in sorted(Path(source_root).rglob("*.py")):
        try:
            numbers = cov._analyze(str(py)).numbers  # line + branch in one call
            exec_lines += numbers.n_statements
            miss_lines += numbers.n_missing
            if numbers.n_branches:
                have_branch = True
                tot_branches += numbers.n_branches
                miss_branches += numbers.n_missing_branches
        except Exception:
            # Fall back to the public per-file API for lines only.
            try:
                analysis = cov.analysis2(str(py))
            except Exception:
                continue
            exec_lines += len(analysis[1])
            miss_lines += len(analysis[3])
        files += 1

    if files == 0:
        return ToolResult(tool="coverage-totals", returncode=2,
                          stderr=f"no .py files under {source_root}")

    covered = exec_lines - miss_lines
    data: dict[str, Any] = {
        "line": {
            "covered": covered,
            "executable": exec_lines,
            "pct": round(covered / exec_lines * 100.0, 2) if exec_lines else 100.0,
        },
        "files_measured": files,
    }
    if have_branch:
        bcov = tot_branches - miss_branches
        data["branch"] = {
            "covered": bcov,
            "total": tot_branches,
            "pct": round(bcov / tot_branches * 100.0, 2) if tot_branches else 100.0,
        }
    return ToolResult(tool="coverage-totals", returncode=0, data=data)


# Subprocess body for the import smoke sweep: put ``source_root`` on sys.path,
# then import every module whose path maps to a valid dotted name (which also
# supports PEP 420 namespace packages — no ``__init__.py`` required — while
# skipping dirs/files with non-identifier names), recording import-time
# failures. ``SystemExit`` at import is caught as a failure (not a crash);
# ``KeyboardInterrupt`` still aborts. Runs isolated so a target module's import
# side effects never touch the engine process.
_IMPORT_SMOKE_SRC = r"""
import importlib, json, sys
from pathlib import Path

src = Path(sys.argv[1]).resolve()
excludes = set(sys.argv[2:])
sys.path.insert(0, str(src))

failures = []
total = 0
for py in sorted(src.rglob("*.py")):
    parts = py.relative_to(src).parts
    if any(p in excludes for p in parts):
        continue
    mod_parts = parts[:-1] if py.name == "__init__.py" else (*parts[:-1], py.stem)
    # a dotted import only resolves when every component is a valid identifier;
    # namespace packages (PEP 420) resolve without __init__.py since src is on path
    if not mod_parts or not all(p.isidentifier() for p in mod_parts):
        continue
    dotted = ".".join(mod_parts)
    total += 1
    try:
        importlib.import_module(dotted)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 - import-time SystemExit etc. IS the signal
        failures.append({"module": dotted, "error": f"{type(exc).__name__}: {exc}"})
print(json.dumps({"total": total, "imported": total - len(failures),
                  "failures": failures}))
"""


def run_import_smoke(
    source_root: Path,
    project_root: Path,
    *,
    exclude: Optional[list[str]] = None,
    timeout: float = 120.0,
) -> ToolResult:
    """Import every source module in a subprocess to catch import-time errors.

    This is the deterministic 'smoke' signal — before any test is authored, does
    the codebase even import? Returns ``{total, imported, failures[]}`` where each
    failure is ``{module, error}``. Runs with ``project_root`` as cwd so imports
    resolve the same way the suite does; degrades to rc=2 if the sweep can't run.
    """
    parts = ["__pycache__", ".git", ".venv"] + list(exclude or [])
    cmd = [sys.executable, "-c", _IMPORT_SMOKE_SRC, str(source_root), *parts]
    try:
        proc = subprocess.run(
            cmd, cwd=str(project_root), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(tool="import-smoke", returncode=124, timed_out=True,
                          stderr=f"import sweep timed out after {timeout}s")
    if proc.returncode != 0:
        return ToolResult(tool="import-smoke", returncode=2,
                          stdout=proc.stdout, stderr=proc.stderr or "import sweep crashed")
    out = proc.stdout.strip()
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        return ToolResult(tool="import-smoke", returncode=2, stdout=proc.stdout,
                          parse_error=f"non-JSON stdout: {exc}")
    return ToolResult(tool="import-smoke", returncode=0, data=data, stdout=proc.stdout)


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
    cwd: Optional[Path] = None,
) -> ToolResult:
    """Re-run one test N times to detect flakiness. ``cwd`` must be the target
    project root so the reruns resolve the project's imports/conftest (the same
    directory used for the green-run)."""
    return _run_module(
        "flakiness_checker.flakiness_checker",
        [test_node_id, "--runs", str(runs), "--timeout", str(timeout_per_run)],
        cwd=cwd,
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
    "Runner",
    "PytestRunner",
    "get_runner",
    "run_lint",
    "run_secret_scan",
    "collect_coverage",
    "run_coverage_gaps",
    "run_import_smoke",
    "run_edges",
    "run_branch_map",
    "run_boundary",
    "run_log_contract",
    "run_assertion_quality",
    "run_mutation",
    "run_flakiness",
    "run_hypothesis_strategies",
]
