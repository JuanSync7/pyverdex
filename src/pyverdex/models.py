"""Cross-stage pydantic contracts for the pyverdex verification engine.

Two groups of models live here:

1. **Engine artifacts** ported from the juansync-synapse ``test-evaluate``
   schema (the source-of-truth cross-skill shapes): ``CoverageState``,
   ``AuditGapReport``, ``IntegrationStrategy`` and friends. These flow between
   LangGraph subgraphs as the hand-off payloads.
2. **Unified coverage** models — the merged, multi-dimensional view
   (line + branch + edge/call-graph + mutation + assertion-quality) that the
   ``report`` node emits. This is the "proper test coverage" output the tool
   exists to produce.

Per-tool output schemas (LintReport, CoverageReport, EdgeCoverageReport, …)
remain alongside each vendored tool under ``tools/vendored/<tool>/schemas.py``
and are imported directly by the adapters.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Engine artifact enums (fixed vocabularies)
# ---------------------------------------------------------------------------


class BoundaryTier(str, Enum):
    runtime = "runtime"
    logical = "logical"
    internal = "internal"


class BoundaryCategory(str, Enum):
    db = "db"
    api = "api"
    queue = "queue"
    file = "file"
    cli = "cli"


class LifecyclePattern(str, Enum):
    transaction_rollback = "transaction-rollback"
    schema_per_test = "schema-per-test"
    vcrpy = "vcrpy"
    ephemeral_container = "ephemeral-container"
    workflow_environment = "workflow-environment"
    celery_test_harness = "celery-test-harness"
    tmp_path = "tmp_path"
    real_fs = "real-fs"
    subprocess_capture = "subprocess-capture"


class ExclusionReason(str, Enum):
    low_marginal_gain = "low-marginal-gain"
    low_failure_mode_risk = "low-failure-mode-risk"
    cost_exceeds_budget = "cost-exceeds-budget"
    over_mocking_warning = "over_mocking_warning"
    wrapper_coupling = "wrapper-coupling"
    already_covered = "already-covered"
    unsupported_category = "unsupported-category"


# ---------------------------------------------------------------------------
# IntegrationStrategy and supporting models (test-evaluate output)
# ---------------------------------------------------------------------------


class BoundarySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_count: int = Field(default=0, ge=0)
    logical_count: int = Field(default=0, ge=0)
    internal_count: int = Field(default=0, ge=0)
    runtime_list: list[str] = Field(default_factory=list)
    logical_list: list[str] = Field(default_factory=list)
    internal_list: list[str] = Field(default_factory=list)


class ReplacementCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    mock_target: str
    boundary_fn: str
    tier: BoundaryTier
    category: BoundaryCategory
    risk: int = Field(ge=1, le=5)
    tier_weight: int = Field(ge=0, le=3)
    risk_weight: int = Field(ge=1, le=5)
    gap: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0)
    pattern: LifecyclePattern
    pattern_rationale: str
    lifecycle_notes: Optional[str] = None


class ExcludedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str
    exclusion_reason: ExclusionReason


class OverMockingWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mock_target: str
    test_file: str
    internal_fn: str


class IntegrationStrategy(BaseModel):
    """Per-module integration strategy emitted by the ``evaluate`` subgraph."""

    model_config = ConfigDict(extra="forbid")

    module_path: str
    module_category: BoundaryCategory
    evaluate_run_id: str
    source_hash: str
    timestamp: datetime
    boundary_summary: BoundarySummary
    candidates_recommended: list[ReplacementCandidate] = Field(default_factory=list)
    candidates_excluded: list[ExcludedCandidate] = Field(default_factory=list)
    over_mocking_warnings: list[OverMockingWarning] = Field(default_factory=list)
    out_of_scope_libs: list[str] = Field(default_factory=list)
    already_real_modules: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# CoverageState + AuditGapReport (shared cross-stage state)
# ---------------------------------------------------------------------------


class ModuleCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_path: str
    has_mocked_integration_tests: bool = False
    has_real_integration_tests: bool = False
    criticality_score: float = Field(default=0.0, ge=0.0)
    source_hash: Optional[str] = None
    integration_strategy_path: Optional[str] = None
    boundary_classification: Optional[BoundarySummary] = None
    evaluate_run_id: Optional[str] = None


class CoverageGapRecord(BaseModel):
    """One actionable gap fed into the ``generate`` subgraph."""

    model_config = ConfigDict(extra="forbid")

    module: str
    function_name: str
    line_start: int
    line_end: int
    coverage_pct: float = Field(ge=0.0, le=100.0)
    missing_lines: list[int] = Field(default_factory=list)
    is_boundary: bool = False
    tier: str = "standard"  # critical | standard | cold
    reason: str = ""  # why this is a gap (below-target line / uncovered branch / …)


class AuditGapReport(BaseModel):
    """Gap report emitted by the ``audit`` subgraph; consumed by generate/evaluate."""

    model_config = ConfigDict(extra="forbid")

    priority_ranking: list[str] = Field(default_factory=list)
    critical_modules: list[str] = Field(default_factory=list)
    gaps: list[CoverageGapRecord] = Field(default_factory=list)


class CoverageState(BaseModel):
    """Engine-wide coverage state persisted at COVERAGE_STATE.yaml."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    generated_at: datetime
    project_root: str
    modules: dict[str, ModuleCoverage] = Field(default_factory=dict)
    audit_gap_report: Optional[AuditGapReport] = None
    last_evaluate_run_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Unified multi-dimensional coverage report (the report node's output)
# ---------------------------------------------------------------------------


class DimensionStatus(str, Enum):
    passed = "pass"
    warn = "warn"
    failed = "fail"
    not_run = "not_run"
    unknown = "unknown"


class FunctionCoverage(BaseModel):
    """All coverage dimensions for a single function, merged into one record."""

    module: str
    function_name: str
    line_start: int = 0
    line_end: int = 0
    tier: str = "standard"  # critical | standard | cold
    is_boundary: bool = False

    # line dimension (coverage.py via coverage_analyzer)
    line_coverage_pct: Optional[float] = None
    missing_lines: list[int] = Field(default_factory=list)

    # branch dimension (branch_mapper — structural enumeration)
    branch_count: Optional[int] = None

    # mutation dimension (mutation_runner — on-demand, may be None)
    mutation_kill_rate: Optional[float] = None
    mutation_survivors: Optional[int] = None

    line_target: Optional[float] = None
    line_status: DimensionStatus = DimensionStatus.not_run


class EdgeRecord(BaseModel):
    caller_module: str
    callee_module: str
    call_site_line: Optional[int] = None


class TestQualityRecord(BaseModel):
    test_id: str
    score: float
    assertion_count: int = 0
    issues: list[str] = Field(default_factory=list)


class DimensionRollup(BaseModel):
    name: str
    status: DimensionStatus
    headline: str
    detail: dict = Field(default_factory=dict)


class UnifiedCoverageReport(BaseModel):
    """The merged, multi-dimensional coverage view — the tool's headline output."""

    project_root: str
    source_root: str
    test_root: str
    generated_at: datetime

    functions: list[FunctionCoverage] = Field(default_factory=list)
    edges: list[EdgeRecord] = Field(default_factory=list)
    test_quality: list[TestQualityRecord] = Field(default_factory=list)

    dimensions: list[DimensionRollup] = Field(default_factory=list)

    # headline metrics
    total_functions: int = 0
    functions_with_line_gaps: int = 0
    boundary_gaps: int = 0
    # whole-codebase coverage (coverage.py over the full source tree) — the honest
    # headline number; counts every line/branch including never-imported files.
    whole_line_coverage_pct: Optional[float] = None
    whole_branch_coverage_pct: Optional[float] = None
    covered_lines: Optional[int] = None
    executable_lines: Optional[int] = None
    # legacy: average line % over *gap functions only* — NOT whole-codebase
    # coverage; retained for backward-compatible consumers. Prefer
    # ``whole_line_coverage_pct`` for the real number.
    overall_line_coverage_pct: Optional[float] = None
    cross_package_edges: int = 0
    mutation_kill_rate: Optional[float] = None
    weak_tests: int = 0
    # real-service integration tests written by the integrate apply path
    integration_tests_written: int = 0
    integration_tests_passed: int = 0

    overall_status: DimensionStatus = DimensionStatus.unknown


__all__ = [
    "BoundaryTier",
    "BoundaryCategory",
    "LifecyclePattern",
    "ExclusionReason",
    "BoundarySummary",
    "ReplacementCandidate",
    "ExcludedCandidate",
    "OverMockingWarning",
    "IntegrationStrategy",
    "ModuleCoverage",
    "CoverageGapRecord",
    "AuditGapReport",
    "CoverageState",
    "DimensionStatus",
    "FunctionCoverage",
    "EdgeRecord",
    "TestQualityRecord",
    "DimensionRollup",
    "UnifiedCoverageReport",
]
