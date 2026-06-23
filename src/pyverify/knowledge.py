"""Load vendored SKILL.md / rules / protocol docs and compose system prompts.

The original juansync-synapse skills *are* flowcharts-as-markdown with rule
files. Each LLM node in the engine is given a system prompt distilled from the
corresponding ``SKILL.md`` plus its ``rules/*.md`` and the governing protocol
contracts (the TDD contract above all). This keeps the LLM nodes faithful to
the original skill's constraints without re-encoding them by hand.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
SKILLS_DIR = KNOWLEDGE_DIR / "skills"
PROTOCOLS_DIR = KNOWLEDGE_DIR / "protocols"
TOOLS_DIR = KNOWLEDGE_DIR / "tools"

# stage name -> vendored skill directory
STAGE_TO_SKILL = {
    "lint": "test-lint",
    "fix": "test-fix",
    "audit": "test-audit",
    "generate": "test-generate",
    "evaluate": "test-evaluate",
    "integrate": "test-integrate",
    "runner": "test-runner",
}


def _read(path: Path) -> str:
    try:
        # strip stray NUL bytes (some upstream docs carry them; they break
        # subprocess argv and prompt encoding)
        return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")
    except OSError:
        return ""


@lru_cache(maxsize=None)
def load_skill_doc(skill_dir: str, *, include_rules: bool = True) -> str:
    """Return SKILL.md (+ rules/*.md) for a vendored skill directory."""
    base = SKILLS_DIR / skill_dir
    parts: list[str] = []
    skill_md = base / "SKILL.md"
    if skill_md.exists():
        parts.append(f"# SKILL: {skill_dir}\n\n{_read(skill_md)}")
    rules_dir = base / "rules"
    if include_rules and rules_dir.is_dir():
        for rule in sorted(rules_dir.glob("*.md")):
            parts.append(f"\n\n## RULE: {rule.stem}\n\n{_read(rule)}")
    return "\n".join(parts).strip()


@lru_cache(maxsize=None)
def load_reference(skill_dir: str, name: str) -> str:
    """Load one references/<name>.md file for a skill (e.g. layer-unit)."""
    return _read(SKILLS_DIR / skill_dir / "references" / f"{name}.md")


@lru_cache(maxsize=None)
def load_protocol(name: str) -> str:
    """Load a governance protocol body (e.g. delivery-execution-tdd-contract)."""
    return _read(PROTOCOLS_DIR / f"{name}.md")


@lru_cache(maxsize=None)
def load_tool_doc(tool: str) -> str:
    return _read(TOOLS_DIR / f"{tool}.md")


_PREAMBLE = (
    "You are a node in pyverify, a deterministic LangGraph test-verification "
    "engine. You execute exactly one skill. Measurement is done by separate "
    "deterministic tools; your job is the judgment/authoring step only. Obey "
    "the skill rules and protocol contracts below verbatim. Never weaken, "
    "skip, or delete tests to force a pass. Return only what the node asks "
    "for — no preamble, no apology."
)


def build_system_prompt(
    stage: str,
    *,
    protocols: tuple[str, ...] = ("delivery-execution-tdd-contract",),
    references: tuple[str, ...] = (),
    extra: str = "",
) -> str:
    """Compose a system prompt for an LLM node from skill + rules + protocols."""
    skill_dir = STAGE_TO_SKILL.get(stage, stage)
    sections = [_PREAMBLE, load_skill_doc(skill_dir)]
    for ref in references:
        body = load_reference(skill_dir, ref)
        if body:
            sections.append(f"\n\n## REFERENCE: {ref}\n\n{body}")
    for proto in protocols:
        body = load_protocol(proto)
        if body:
            sections.append(f"\n\n## PROTOCOL: {proto}\n\n{body}")
    if extra:
        sections.append(f"\n\n## NODE INSTRUCTIONS\n\n{extra}")
    return "\n".join(s for s in sections if s).strip()


__all__ = [
    "KNOWLEDGE_DIR",
    "STAGE_TO_SKILL",
    "load_skill_doc",
    "load_reference",
    "load_protocol",
    "load_tool_doc",
    "build_system_prompt",
]
