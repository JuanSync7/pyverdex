"""Configuration model for the pyverify engine.

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
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    def line_target(self, tier: str) -> float:
        return {
            "critical": self.line_critical,
            "standard": self.line_standard,
            "cold": self.line_cold,
        }.get(tier, self.line_standard)


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


class GenerateConfig(BaseModel):
    """Apply-mode for the generate stage."""

    apply: bool = False  # write approved tests to disk + re-audit (closes the loop)
    restrengthen_attempts: int = 1  # re-author cycles when mutants survive
    mutation_max_lines: int = 20
    mutation_timeout: float = 30.0  # per-mutant seconds
    generated_subdir: str = "pyverify_generated"  # under test_root


class LoopConfig(BaseModel):
    max_cycles: int = 3  # audit→generate→audit loop bound
    max_gaps_per_cycle: int = 10


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


class Config(BaseSettings):
    """Top-level engine configuration.

    Field values may be overridden by environment variables prefixed
    ``PYVERIFY_`` (e.g. ``PYVERIFY_PROJECT_ROOT``). Nested values use a
    double-underscore delimiter, e.g. ``PYVERIFY_MODEL__MODEL``.
    """

    model_config = SettingsConfigDict(
        env_prefix="PYVERIFY_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    project_root: str = "."
    paths: PathsConfig = Field(default_factory=PathsConfig)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    model: ModelConfig = Field(default_factory=ModelConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    generate: GenerateConfig = Field(default_factory=GenerateConfig)
    stages: dict[StageName, StageConfig] = Field(default_factory=_default_stages)

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
    "LoopConfig",
    "PathsConfig",
    "Config",
]
