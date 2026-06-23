"""`generate` subgraph — author tests for audit gaps under gates (apply-mode).

Flow: ``[SELECT] -> [AUTHOR] -> [GATE] -> [APPLY]``.

- AUTHOR: an LLM backend (Anthropic API or Claude Code headless) writes one
  pytest test per below-target gap, guided by a system prompt distilled from
  the test-generate SKILL.md + assertion-policy / layer-unit + the TDD contract.
- GATE: per-stage human approval (LangGraph ``interrupt()`` when gated).
- APPLY (when ``generate.apply`` is on and approved): for each gap, write the
  test, then gate it through ``[VALIDATE] -> [GREEN-RUN] -> [MUTATE]`` — it must
  parse, pass when run, and reach ``mutation_kill_rate`` under ``mutation_runner``
  or the node re-authors (``restrengthen_attempts``) with the failure / surviving
  mutants as feedback. Authored functions are recorded in ``gen_handled`` so the
  audit⇄generate loop re-measures (coverage improves) without re-authoring the
  same gap; the loop ends when no unhandled gaps remain or ``loop.max_cycles``.

With ``apply`` off (default) the stage is propose-only: candidates are surfaced
for the gate and recorded, but no files are written.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..backends import LLMBackend
from ..config import Config, StageName
from ..knowledge import build_system_prompt
from ..state import EngineState
from ..tools import adapters
from ._gates import human_gate

_FENCE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def _strip_code(text: str) -> str:
    """Extract Python from an LLM reply: prefer the largest fenced block, else
    the whole text. Surrounding prose (a common LLM habit) is discarded."""
    text = (text or "").replace("\x00", "")
    blocks = _FENCE_BLOCK.findall(text)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip() + "\n"


def _valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _green_run(root: Path, test_path: Path, timeout: float = 120.0) -> tuple[bool, str]:
    """Run pytest on one test file; (passed, short_output). rc 0 == green."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q",
             "-p", "no:cacheprovider"],
            cwd=str(root), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "green-run timed out"
    return proc.returncode == 0, (proc.stdout or proc.stderr)[-500:]


def _module_file(source_root: Path, dotted: str) -> Path:
    return source_root.joinpath(*dotted.split(".")).with_suffix(".py")


def _test_path(test_root: Path, subdir: str, module: str, fn: str) -> Path:
    slug = module.replace(".", "_")
    return test_root / subdir / f"test_{slug}_{fn}.py"


def build_generate_graph(config: Config, backend: LLMBackend | None = None):
    max_gaps = config.loop.max_gaps_per_cycle
    gen = config.generate
    kill_target = config.thresholds.mutation_kill_rate

    def _unhandled_below_target(state: EngineState) -> list[dict]:
        handled = set(state.get("gen_handled", []))
        gaps = (state.get("audit_gap_report") or {}).get("gaps", [])
        out = []
        for g in gaps:
            if "<" not in g.get("reason", ""):
                continue
            if f"{g['module']}::{g['function_name']}" in handled:
                continue
            out.append(g)
        return out[:max_gaps]

    def _author_one(system: str, g: dict, feedback: str = "") -> str:
        prompt = (
            "Write ONE pytest test module (descriptive docstring, at least "
            f"{config.thresholds.assertion_min} meaningful assertions) covering the "
            f"uncovered lines of `{g['function_name']}` in module `{g['module']}` "
            f"(currently {g.get('coverage_pct')}% line coverage; missing lines "
            f"{g.get('missing_lines')}). Import the function under test. "
            "Output ONLY a complete runnable Python test module in a single ```python "
            "code block — no commentary."
        )
        if feedback:
            prompt += f"\n\nThe previous attempt was rejected: {feedback}"
        return _strip_code(backend.invoke(prompt, system=system))

    # ---- nodes ----------------------------------------------------------

    def select(state: EngineState) -> dict:
        sel = _unhandled_below_target(state)
        return {"log": [f"generate/select: {len(sel)} unhandled below-target gaps"]}

    def author(state: EngineState) -> dict:
        sel = _unhandled_below_target(state)
        cycle = state.get("cycle", 0) + 1
        if not sel:
            return {"cycle": cycle, "loop_exhausted": True, "gen_pending": [],
                    "log": ["generate/author: no unhandled gaps; loop exhausted"]}
        if backend is None or not config.is_enabled(StageName.generate):
            return {"cycle": cycle, "loop_exhausted": True, "gen_pending": [],
                    "log": [f"generate/author: {len(sel)} gaps need tests (skipped — "
                            "no LLM backend / stage disabled)"]}
        system = build_system_prompt(
            "generate", references=("layer-unit", "assertion-policy"))
        pending = []
        for g in sel:
            try:
                code = _author_one(system, g)
            except Exception as exc:  # noqa: BLE001
                return {"cycle": cycle, "loop_exhausted": True, "gen_pending": [],
                        "errors": [f"generate/author: backend error: {exc}"]}
            pending.append({"module": g["module"], "function_name": g["function_name"],
                            "tier": g.get("tier"), "coverage_pct": g.get("coverage_pct"),
                            "missing_lines": g.get("missing_lines"),
                            "proposed_test": code, "mutation_kill_rate": None})
        return {"cycle": cycle, "gen_pending": pending,
                "log": [f"generate/author: drafted {len(pending)} tests via "
                        f"{backend.name} backend"]}

    def gate(state: EngineState) -> dict:
        pending = state.get("gen_pending", [])
        decision = human_gate(config, StageName.generate, {
            "proposed_tests": len(pending),
            "modules": sorted({p["module"] for p in pending}),
            "apply": gen.apply,
        })
        return {"approvals": {**state.get("approvals", {}), "generate": decision},
                "log": [f"generate/gate: approve={decision.get('approve')}"]}

    def _finalize_gap(state: EngineState, p: dict, system: str) -> tuple[dict, str]:
        source = Path(state["source_root"])
        root = Path(state["project_root"])
        test_root = Path(state["test_root"])
        module, fn = p["module"], p["function_name"]
        tpath = _test_path(test_root, gen.generated_subdir, module, fn)
        tpath.parent.mkdir(parents=True, exist_ok=True)
        mod_file = _module_file(source, module)

        code = p["proposed_test"]
        kill_rate, survivors, status = None, None, "unknown"
        attempts = gen.restrengthen_attempts + 1
        for attempt in range(attempts):
            tpath.write_text(code, encoding="utf-8")
            feedback = ""
            if not _valid_python(code):
                status, feedback = "syntax-error", "output was not valid Python."
            elif (gr := _green_run(root, tpath))[0] is False:
                status, feedback = "red", f"the test failed when run:\n{gr[1]}"
            elif not mod_file.exists():
                status = "module-not-found"
                break
            else:
                res = adapters.run_mutation(
                    mod_file, function=fn, max_lines=gen.mutation_max_lines,
                    timeout_per_mutant=gen.mutation_timeout, cwd=root)
                if not res.ok or res.data is None:
                    status = "mutation-error"
                    break
                kill_rate = res.data.get("kill_rate")
                survivors = res.data.get("survived")
                if kill_rate is not None and kill_rate >= kill_target:
                    status = "pass"
                    break
                alive = [r["mutant"]["mutated_code"] for r in res.data.get("results", [])
                         if not r.get("killed")][:8]
                status = "survived"
                feedback = "these mutants survived; strengthen assertions:\n" + \
                    "\n".join(f"- {m}" for m in alive)
            # restrengthen unless out of attempts
            if attempt < attempts - 1 and feedback:
                try:
                    code = _author_one(system, p, feedback=feedback)
                except Exception as exc:  # noqa: BLE001
                    status = f"reauthor-error: {exc}"
                    break
            else:
                break

        rec = {**p, "test_path": str(tpath), "mutation_kill_rate": kill_rate,
               "mutation_survivors": survivors, "gate": status}
        rec.pop("proposed_test", None)
        log = (f"generate/apply: {module}.{fn} -> {tpath.name} [{status}"
               + (f", kill={kill_rate:.0%}]" if isinstance(kill_rate, float) else "]"))
        return rec, log

    def apply(state: EngineState) -> dict:
        pending = state.get("gen_pending", [])
        approved = state.get("approvals", {}).get("generate", {}).get("approve", False)
        handled = list(state.get("gen_handled", []))

        if not pending:
            return {"loop_exhausted": True, "log": ["generate/apply: nothing pending"]}
        if not approved:
            return {"gen_pending": [], "loop_exhausted": True,
                    "log": ["generate/apply: batch rejected at gate; discarded"]}
        if not gen.apply:
            return {"generated": [*state.get("generated", []), *pending],
                    "gen_pending": [], "loop_exhausted": True,
                    "log": [f"generate/apply: propose-only, recorded {len(pending)} "
                            "drafts (set generate.apply=true to write + gate)"]}

        system = build_system_prompt("generate", references=("assertion-policy",))
        finalized, logs = [], []
        for p in pending:
            rec, log = _finalize_gap(state, p, system)
            finalized.append(rec)
            logs.append(log)
            handled.append(f"{p['module']}::{p['function_name']}")

        return {"generated": [*state.get("generated", []), *finalized],
                "gen_pending": [], "gen_handled": handled, "loop_exhausted": False,
                "log": logs}

    g = StateGraph(EngineState)
    g.add_node("select", select)
    g.add_node("author", author)
    g.add_node("gate", gate)
    g.add_node("apply", apply)
    g.add_edge(START, "select")
    g.add_edge("select", "author")
    g.add_edge("author", "gate")
    g.add_edge("gate", "apply")
    g.add_edge("apply", END)
    return g.compile()


__all__ = ["build_generate_graph"]
