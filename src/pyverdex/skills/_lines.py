"""Which lines prove a piece of code ran (Phase I).

Coverage data says "this line ran under this test". It does not say *which
code* ran it: ``def helper(cb=lambda: 1):`` is one line that the enclosing
function emits when it defines the helper and the lambda emits when someone
calls it later. Guessing from the syntax tree which lines are safe went wrong
case after case, so this module asks the compiler instead.

The module source is compiled (never executed) and every code object's line
table is read. A line is an **anchor** for a function only when that
function's code object is the *only* one that can emit it — then a line event
there proves that code ran. The ``def`` line, decorators, nested functions,
classes, lambdas, comprehensions and generator expressions all drop out with
no special case: each shares its lines with another code object.

A verdict has three values (:func:`judge`):

- ``True``  — a named test ran an anchor line;
- ``False`` — nothing ran an anchor, *and* the first line the code emits on
  entry is an anchor, so entering it could not have gone unseen;
- ``None``  — anything else. Unknown is never reported as a zero.

Limit: line tables are those of the interpreter running pyverdex, which is
also the one that runs the target's tests (``sys.executable``).
"""

from __future__ import annotations

import ast
import dis
import warnings
from dataclasses import dataclass
from types import CodeType
from typing import Iterator, Optional


@dataclass(frozen=True)
class Anchors:
    """Lines only one piece of code can emit, and its entry line if that is
    one of them (else None)."""

    lines: frozenset[int] = frozenset()
    entry: Optional[int] = None


NO_ANCHORS = Anchors()


def judge(anchors: Anchors,
          labelled: dict[int, set[str]]) -> tuple[Optional[bool], list[str]]:
    """``(verdict, tests)`` for one piece of code against ``{line: {test
    labels}}`` of its module."""
    tests: set[str] = set()
    for line in anchors.lines:
        tests.update(labelled.get(line, ()))
    if tests:
        return True, sorted(tests)
    if anchors.entry is not None:
        return False, []
    return None, []


def _code_objects(code: CodeType) -> Iterator[CodeType]:
    yield code
    for const in code.co_consts:
        if isinstance(const, CodeType):
            yield from _code_objects(const)


def _emitted(code: CodeType) -> set[int]:
    return {line for _, _, line in code.co_lines() if line is not None}


def _instruction_lines(code: CodeType) -> Iterator[tuple[str, Optional[int]]]:
    """``(opname, line)`` in bytecode order."""
    for ins in dis.get_instructions(code):
        positions = ins.positions
        yield ins.opname, (positions.lineno if positions is not None else None)


def _entry_line(code: CodeType) -> Optional[int]:
    """Line of the first instruction after the function's opening RESUME —
    the first line event a call produces. None when it cannot be told."""
    resumed = False
    for opname, line in _instruction_lines(code):
        if not resumed:
            resumed = opname == "RESUME"
            continue
        return line
    return None


class ModuleCode:
    """The compiled line tables of one module's source."""

    def __init__(self, source: str) -> None:
        self._by_start: dict[tuple[str, int], list[CodeType]] = {}
        self._emitters: dict[int, int] = {}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                top = compile(source, "<pyverdex-lines>", "exec",
                              dont_inherit=True)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return  # no tables -> no anchors -> every verdict is unknown
        for code in _code_objects(top):
            self._by_start.setdefault(
                (code.co_name, code.co_firstlineno), []).append(code)
            for line in _emitted(code):
                self._emitters[line] = self._emitters.get(line, 0) + 1

    def _code_for(self, fn: ast.FunctionDef | ast.AsyncFunctionDef
                  ) -> Optional[CodeType]:
        # a decorated function's code starts at its first decorator
        start = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
        found = self._by_start.get((fn.name, start), [])
        return found[0] if len(found) == 1 else None

    def _only_here(self, code: CodeType) -> set[int]:
        return {line for line in _emitted(code) if self._emitters.get(line) == 1}

    def function_anchors(self, fn: ast.FunctionDef | ast.AsyncFunctionDef
                         ) -> Anchors:
        """Anchors proving the function's own body ran."""
        code = self._code_for(fn)
        if code is None:
            return NO_ANCHORS
        lines = self._only_here(code)
        entry = _entry_line(code)
        return Anchors(frozenset(lines), entry if entry in lines else None)

    def handler_anchors(self, fn: ast.FunctionDef | ast.AsyncFunctionDef,
                        handler: ast.ExceptHandler) -> Anchors:
        """Anchors proving this except-handler's *body* ran. Header lines are
        left out (the type test runs them without entering the body), however
        many lines the header spans."""
        code = self._code_for(fn)
        if code is None or not handler.body:
            return NO_ANCHORS
        start = handler.body[0].lineno
        end = max(int(getattr(s, "end_lineno", None) or s.lineno)
                  for s in handler.body)
        header_end = handler.lineno
        if handler.type is not None:
            header_end = int(getattr(handler.type, "end_lineno", None)
                             or handler.lineno)
        lines = {line for line in self._only_here(code)
                 if start <= line <= end and not handler.lineno <= line <= header_end}
        # the first instruction, in bytecode order, that belongs to the body
        entry: Optional[int] = None
        for _, line in _instruction_lines(code):
            if line is not None and start <= line <= end:
                entry = line
                break
        return Anchors(frozenset(lines), entry if entry in lines else None)


__all__ = ["Anchors", "NO_ANCHORS", "ModuleCode", "judge"]
