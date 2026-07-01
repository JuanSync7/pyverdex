"""Configuration model for the pyverdex engine.

A single YAML (or env-overridable) config drives every threshold, which
stages run, whether each gate is a blocking human approval or automatic, and
the audit⇄generate loop bound. This replaces the constants that were
scattered across the original juansync-synapse tools and SKILL.md files.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import TestLevel


class GateMode(str, Enum):
    """Per-stage human-in-the-loop behaviour."""

    gated = "gated"  # LangGraph interrupt() — block for human approval
    auto = "auto"  # proceed without interruption


class StageName(str, Enum):
    lint = "lint"
    fix = "fix"
    audit = "audit"
    generate = "generate"
    evaluate = "evaluate"
    integrate = "integrate"
    report = "report"


class Thresholds(BaseModel):
    """Coverage / quality gate thresholds. Tier targets mirror the original
    test-audit defaults (critical 95 / standard 85 / cold 70)."""

    line_critical: float = 95.0
    line_standard: float = 85.0
    line_cold: float = 70.0
    mutation_kill_rate: float = 1.0  # generate gate: mutants must be 100% killed
    assertion_score: float = 0.5
    assertion_min: int = 2
    flakiness_max_fail_rate: float = 0.02
    flakiness_min_runs: int = 10
    edge_coverage_min: float = 0.0  # advisory by default
    cold_paths: list[str] = Field(
        default_factory=list,
        description="Module-path substrings whose non-boundary functions use the "
        "lower 'cold' line target, e.g. ['_internal', 'experimental']. Makes the "
        "cold tier reachable; empty means no function is classified cold.",
    )

    @field_validator("line_critical", "line_standard", "line_cold")
    @classmethod
    def _is_percent(cls, v: float) -> float:
        if not 0.0 <= v <= 100.0:
            raise ValueError("line target must be a percentage in [0, 100]")
        return v

    @field_validator("mutation_kill_rate", "flakiness_max_fail_rate")
    @classmethod
    def _is_rate(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("must be a rate in [0.0, 1.0]")
        return v

    @field_validator("assertion_score", "edge_coverage_min", "assertion_min")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be non-negative")
        return v

    @field_validator("flakiness_min_runs")
    @classmethod
    def _at_least_one_run(cls, v: int) -> int:
        if v < 1:
            raise ValueError("flakiness_min_runs must be >= 1")
        return v

    def line_target(self, tier: str) -> float:
        return {
            "critical": self.line_critical,
            "standard": self.line_standard,
            "cold": self.line_cold,
        }.get(tier, self.line_standard)

    def tier_for(self, *, is_boundary: bool, module: str = "") -> str:
        """Classify a function into a coverage tier (single source of truth).

        Boundary (runtime-exposed) functions are ``critical``; non-boundary
        functions whose module matches a configured ``cold_paths`` substring are
        ``cold``; everything else is ``standard``. Both the ``audit`` score node
        and the report builder call this, so their tiering cannot drift.
        """
        if is_boundary:
            return "critical"
        if any(p and p in module for p in self.cold_paths):
            return "cold"
        return "standard"


class StageConfig(BaseModel):
    enabled: bool = True
    gate: GateMode = GateMode.gated


class ModelConfig(BaseModel):
    """LLM used by the judgment nodes (fix / generate / evaluate / integrate)."""

    provider: str = "anthropic"  # "anthropic" | "claude-code" | "fake"
    model: str = "claude-sonnet-4-6"  # Anthropic API model id
    claude_code_model: Optional[str] = None  # claude CLI alias (e.g. "sonnet"); None => CLI default
    temperature: float = 0.0
    max_tokens: int = 8000

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        allowed = {"anthropic", "claude-code", "fake"}
        if v not in allowed:
            raise ValueError(f"provider must be one of {sorted(allowed)}")
        return v

    @field_validator("temperature")
    @classmethod
    def _valid_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature must be in [0.0, 2.0]")
        return v

    @field_validator("max_tokens")
    @classmethod
    def _positive_tokens(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_tokens must be positive")
        return v


class GenerateConfig(BaseModel):
    """Apply-mode for the generate stage."""

    apply: bool = False  # write approved tests to disk + re-audit (closes the loop)
    restrengthen_attempts: int = 1  # re-author cycles when mutants survive
    mutation_max_lines: int = 20
    mutation_timeout: float = 30.0  # per-mutant seconds
    generated_subdir: str = "pyverdex_generated"  # under test_root

    @field_validator("restrengthen_attempts", "mutation_max_lines")
    @classmethod
    def _positive_counts(cls, v: int, info: Any) -> int:
        floor = 0 if info.field_name == "restrengthen_attempts" else 1
        if v < floor:
            raise ValueError(f"{info.field_name} must be >= {floor}")
        return v

    @field_validator("mutation_timeout")
    @classmethod
    def _positive_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("mutation_timeout must be positive")
        return v


class IntegrateConfig(BaseModel):
    """Apply-mode for the integrate stage (real-service tests)."""

    apply: bool = False  # write proposed integration tests to disk + gate them
    generated_subdir: str = "pyverdex_integration"  # under test_root (kept separate)


class AuditConfig(BaseModel):
    """Toggles for the (deterministic) audit measurement stage."""

    import_smoke: bool = True  # import every source module to catch import-time errors
    import_smoke_timeout: float = 120.0  # seconds for the whole import sweep

    @field_validator("import_smoke_timeout")
    @classmethod
    def _positive_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("import_smoke_timeout must be positive")
        return v


class LoopConfig(BaseModel):
    max_cycles: int = 3  # audit→generate→audit loop bound
    max_gaps_per_cycle: int = 10

    @field_validator("max_cycles", "max_gaps_per_cycle")
    @classmethod
    def _at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v


class PathsConfig(BaseModel):
    source_root: str = "src"
    test_root: str = "tests"
    state_dir: str = "project/coverage/state"
    report_dir: str = "project/coverage/report"
    checkpoint_db: str = "project/coverage/state/checkpoints.sqlite"


def _default_stages() -> dict[StageName, StageConfig]:
    return {
        StageName.lint: StageConfig(gate=GateMode.auto),
        StageName.fix: StageConfig(gate=GateMode.gated),
        StageName.audit: StageConfig(gate=GateMode.auto),
        StageName.generate: StageConfig(gate=GateMode.gated),
        StageName.evaluate: StageConfig(gate=GateMode.auto),
        StageName.integrate: StageConfig(gate=GateMode.gated),
        StageName.report: StageConfig(gate=GateMode.auto),
    }


# Which stages each TestLevel needs. ``audit`` (measurement) and ``report``
# (output) are always on; each level adds the stage that *produces* its kind of
# test. Levels are ORTHOGONAL to coverage tiers (Thresholds): a level selects
# which stages run, a tier sets the bar a stage must clear. See ADR 0002.
# ``lint``/``fix`` are pre-flight, not a test level, so a level filter drops them.
LEVEL_STAGES: dict[TestLevel, set[StageName]] = {
    TestLevel.smoke: {StageName.audit, StageName.report},
    TestLevel.unit: {StageName.audit, StageName.generate, StageName.report},
    TestLevel.integration: {
        StageName.audit, StageName.evaluate, StageName.integrate, StageName.report},
    # e2e is reserved: no dedicated harness yet, so it aliases the integration
    # pipeline for now (documented in ADR 0002 rather than silently faked).
    TestLevel.e2e: {
        StageName.audit, StageName.evaluate, StageName.integrate, StageName.report},
}


def parse_levels(spec: str) -> list[TestLevel]:
    """Parse a comma-separated ``--level`` spec into TestLevel members.

    Raises ``ValueError`` naming the offending token (and the valid set) so the
    CLI/server can surface a clean message instead of a stack trace.
    """
    out: list[TestLevel] = []
    for raw in spec.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        try:
            lvl = TestLevel(token)
        except ValueError:
            valid = ", ".join(t.value for t in TestLevel)
            raise ValueError(f"unknown test level '{token}'; choose from: {valid}") from None
        if lvl not in out:
            out.append(lvl)
    if not out:
        raise ValueError("no test level given")
    return out


class Config(BaseSettings):
    """Top-level engine configuration.

    Field values may be overridden by environment variables prefixed
    ``PYVERDEX_`` (e.g. ``PYVERDEX_PROJECT_ROOT``). Nested values use a
    double-underscore delimiter, e.g. ``PYVERDEX_MODEL__MODEL``.
    """

    model_config = SettingsConfigDict(
        env_prefix="PYVERDEX_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    project_root: str = "."
    paths: PathsConfig = Field(default_factory=PathsConfig)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    model: ModelConfig = Field(default_factory=ModelConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    generate: GenerateConfig = Field(default_factory=GenerateConfig)
    integrate: IntegrateConfig = Field(default_factory=IntegrateConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    stages: dict[StageName, StageConfig] = Field(default_factory=_default_stages)
    # which test runner backs coverage/green-runs; "pytest" is the only one today
    # (the seam for unittest/other runners — see ADR 0003). Kept in sync with
    # adapters._RUNNERS; validated at load so a typo fails fast, not mid-run.
    runner: str = "pytest"

    @field_validator("runner")
    @classmethod
    def _known_runner(cls, v: str) -> str:
        if v not in {"pytest"}:
            raise ValueError("runner must be 'pytest' (the only runner today)")
        return v

    # --- derived absolute paths -------------------------------------------

    @property
    def root(self) -> Path:
        return Path(self.project_root).resolve()

    @property
    def abs_source_root(self) -> Path:
        return (self.root / self.paths.source_root).resolve()

    @property
    def abs_test_root(self) -> Path:
        return (self.root / self.paths.test_root).resolve()

    @property
    def abs_state_dir(self) -> Path:
        return (self.root / self.paths.state_dir).resolve()

    @property
    def abs_report_dir(self) -> Path:
        return (self.root / self.paths.report_dir).resolve()

    @property
    def abs_checkpoint_db(self) -> Path:
        return (self.root / self.paths.checkpoint_db).resolve()

    def stage(self, name: StageName) -> StageConfig:
        return self.stages.get(name, StageConfig())

    def is_enabled(self, name: StageName) -> bool:
        return self.stage(name).enabled

    def is_gated(self, name: StageName) -> bool:
        return self.stage(name).gate is GateMode.gated

    def apply_levels(self, levels: list[TestLevel]) -> None:
        """Restrict the run to the stages the given test levels need.

        Enables exactly the union of ``LEVEL_STAGES`` for the selected levels
        (disabling every other stage) while preserving each stage's gate mode.
        Coverage thresholds are untouched — levels and tiers are orthogonal.
        """
        wanted: set[StageName] = set()
        for lvl in levels:
            wanted |= LEVEL_STAGES.get(lvl, set())
        self.stages = {n: self.stage(n).model_copy(update={"enabled": n in wanted})
                       for n in StageName}

    def ensure_dirs(self) -> None:
        self.abs_state_dir.mkdir(parents=True, exist_ok=True)
        self.abs_report_dir.mkdir(parents=True, exist_ok=True)

    # --- loaders -----------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(**data)

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        """Load from YAML if a path is given, else use defaults + env overrides."""
        if path:
            return cls.from_yaml(path)
        return cls()


__all__ = [
    "GateMode",
    "StageName",
    "Thresholds",
    "StageConfig",
    "ModelConfig",
    "GenerateConfig",
    "IntegrateConfig",
    "AuditConfig",
    "LoopConfig",
    "PathsConfig",
    "Config",
    "LEVEL_STAGES",
    "parse_levels",
]
