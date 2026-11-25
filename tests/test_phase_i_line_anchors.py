"""Phase I — which lines prove a factory or a handler ran.

The two Phase I measurements read "a named test ran this" off line numbers.
That is only sound when the line can be emitted by that code and no other,
so these tests check the rule against a real tracer over many generated
bodies, instead of against the cases someone already thought of:

- the code did not run under the test  -> the verdict is never True;
- the code did run under the test      -> the verdict is never False;
- plain bodies still resolve to True / False (unknown everywhere would pass
  the first two).
"""

from __future__ import annotations

import ast
import itertools
import sys
import textwrap
from typing import Callable, Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from pyverdex.skills import _failpaths, _lines

LABEL = "test_mod.test_x"

PRELUDE = (
    "calls = []\n"
    "out = []\n"
    "Z = 0\n"
    "def deco(fn):\n"
    "    return fn\n"
    "def boom():\n"
    "    raise RuntimeError('boom')\n"
    "class ctxm:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
)

# Body statements. Anything callable later is appended to ``out`` so a test
# can run it without running the enclosing body again.
FRAGMENTS: list[str] = [
    "x = 1",
    "(\n    calls.append(1)\n)",
    "def helper(cb=lambda: 1):\n    return cb\nout.append(helper())",
    "def helper2(\n    cb=lambda: 1,\n):\n    return cb\nout.append(helper2())",
    "out.append(lambda: 1)",
    "out.append(\n    lambda: 1\n)",
    "out.append(lambda: (\n    1\n))",
    "out.append((i for i in range(2)).__next__)",
    "out.append(\n    (i for i in range(2)).__next__\n)",
    "class K:\n    def m(self): return 1\nout.append(K().m)",
    "class K2:\n    def m(self):\n        return 1\nout.append(K2().m)",
    '"""doc"""',
    "global Z",
    "def one(): return 1\nout.append(one)",
    "def two():\n    return 2\nout.append(two)",
    "@deco\ndef three():\n    return 3\nout.append(three)",
    "y = [i for i in range(2)]",
    "if calls is not None:\n    z = (\n        2\n    )",
    "pass",
    "raise RuntimeError('boom')",
    "out.append(boom() or (lambda: 1))",
    "return 1",
    "with ctxm():\n    w = 1",
    "for i in range(1):\n    q = i",
    "try:\n    pass\nexcept ValueError:\n    r = 1\nfinally:\n    s = 1",
    "async def co(): return 1",
]

FACTORY_FORMS = ["block", "signature", "decorated", "inline", "signature_inline"]
FACTORY_MODES = ["called", "deferred", "idle"]
HANDLER_FORMS = ["block", "as", "multiline", "inline", "multiline_inline",
                 "inline_wrapped"]
SIBLINGS = ["none", "block", "inline"]
HANDLER_MODES = ["hit", "sibling", "miss", "deferred", "idle"]


def _body(frags: list[int], indent: int) -> str:
    text = "\n".join(FRAGMENTS[i] for i in frags) + "\n"
    return textwrap.indent(text, " " * indent)


def factory_source(form: str, frags: list[int]) -> str:
    if form == "inline":
        return PRELUDE + "def create_app(): return calls.append(1)\n"
    if form == "signature_inline":
        return PRELUDE + "def create_app(\n    value=1,\n): return calls.append(1)\n"
    head = {"block": "def create_app():\n",
            "signature": "def create_app(\n    value=1,\n):\n",
            "decorated": "@deco\ndef create_app():\n"}[form]
    return PRELUDE + head + _body(frags, 4)


def handler_source(form: str, sibling: str, frags: list[int]) -> str:
    head = "def f(kind):\n    try:\n        raise kind()\n"
    if form == "inline":
        first = "    except KeyError: calls.append(1)\n"
    elif form == "multiline_inline":
        first = "    except (\n        KeyError\n    ): calls.append(1)\n"
    elif form == "inline_wrapped":
        first = "    except KeyError: return (\n        0)\n"
    else:
        header = {"block": "    except KeyError:\n",
                  "as": "    except KeyError as e:\n",
                  "multiline": "    except (\n        KeyError\n    ):\n"}[form]
        first = header + _body(frags, 8)
    second = {"none": "",
              "block": "    except TypeError:\n        return 2\n",
              "inline": "    except TypeError: return 2\n"}[sibling]
    return PRELUDE + head + first + second


_counter = itertools.count()


def _quiet(fn: Callable, *args) -> None:
    try:
        fn(*args)
    except Exception:  # the bodies raise on purpose
        pass


def run_traced(src: str, at_import: Callable[[dict], None],
               in_test: Callable[[dict], None]):
    """Execute ``src``, then run ``in_test`` under a tracer.

    Returns ``(env, labelled, called)``: the line -> labels data the code
    under test is given, and — the oracle it is NOT given — the code objects
    whose frames ran during the test."""
    filename = f"<anchors-{next(_counter)}>"
    env: dict = {}
    exec(compile(src, filename, "exec"), env)
    at_import(env)
    labelled: dict[int, set[str]] = {}
    called: set = set()

    def tracer(frame, event, arg):
        if frame.f_code.co_filename == filename:
            if event == "call":
                called.add(frame.f_code)
            elif event == "line":
                labelled.setdefault(frame.f_lineno, set()).add(LABEL)
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        in_test(env)
    finally:
        sys.settrace(previous)
    return env, labelled, called


def _run_deferred(env: dict) -> None:
    for item in list(env["out"]):
        _quiet(item)


def _fn_node(src: str, name: str) -> ast.FunctionDef:
    return next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == name)


def factory_verdict(src: str, labelled: dict[int, set[str]]) -> Optional[bool]:
    anchors = _lines.ModuleCode(src).function_anchors(_fn_node(src, "create_app"))
    return _lines.judge(anchors, labelled)[0]


def handler_verdicts(src: str, labelled: dict[int, set[str]]) -> list[Optional[bool]]:
    fn = _fn_node(src, "f")
    module = _lines.ModuleCode(src)
    try_node = next(n for n in fn.body if isinstance(n, ast.Try))
    return [_lines.judge(module.handler_anchors(fn, h), labelled)[0]
            for h in try_node.handlers]


def check_factory(form: str, frags: list[int], mode: str,
                  verdict: Callable = factory_verdict) -> Optional[bool]:
    src = factory_source(form, frags)
    if mode == "called":
        at_import, in_test = (lambda e: None), (lambda e: _quiet(e["create_app"]))
    elif mode == "deferred":
        at_import, in_test = (lambda e: _quiet(e["create_app"])), _run_deferred
    else:
        at_import, in_test = (lambda e: None), (lambda e: e["deco"](None))
    env, labelled, called = run_traced(src, at_import, in_test)
    ran = env["create_app"].__code__ in called
    got = verdict(src, labelled)
    assert ran == (mode == "called")
    if ran:
        assert got is not False, f"ran under the test but read as not run:\n{src}"
    else:
        assert got is not True, f"did not run under the test but credited:\n{src}"
    return got


def check_handler(form: str, sibling: str, frags: list[int], mode: str,
                  verdicts: Callable = handler_verdicts) -> list[Optional[bool]]:
    src = handler_source(form, sibling, frags)
    kind = {"hit": KeyError, "sibling": TypeError, "miss": ValueError}.get(mode)
    if kind is not None:
        at_import, in_test = (lambda e: None), (lambda e: _quiet(e["f"], kind))
    elif mode == "deferred":
        at_import, in_test = (lambda e: _quiet(e["f"], KeyError)), _run_deferred
    else:
        at_import, in_test = (lambda e: None), (lambda e: e["deco"](None))
    _, labelled, _ = run_traced(src, at_import, in_test)
    entered = [mode == "hit"]
    if sibling != "none":
        entered.append(mode == "sibling")
    got = verdicts(src, labelled)
    assert len(got) == len(entered)
    for one, truth in zip(got, entered):
        if truth:
            assert one is not False, f"handler ran but read as not run:\n{src}"
        else:
            assert one is not True, f"handler did not run but credited:\n{src}"
    boundary = _failpaths.boundary_verdict(got)
    if any(entered):
        assert boundary is not False, f"boundary read as a measured zero:\n{src}"
    else:
        assert boundary is not True, f"boundary credited with no handler run:\n{src}"
    return got


_frags = st.lists(st.integers(0, len(FRAGMENTS) - 1), min_size=1, max_size=4)
_settings = settings(max_examples=400, derandomize=True, deadline=None,
                     database=None)


@_settings
@given(form=st.sampled_from(FACTORY_FORMS), frags=_frags,
       mode=st.sampled_from(FACTORY_MODES))
def test_factory_verdict_never_contradicts_the_tracer(form, frags, mode):
    check_factory(form, frags, mode)


@_settings
@given(form=st.sampled_from(HANDLER_FORMS), sibling=st.sampled_from(SIBLINGS),
       frags=_frags, mode=st.sampled_from(HANDLER_MODES))
def test_handler_verdict_never_contradicts_the_tracer(form, sibling, frags, mode):
    check_handler(form, sibling, frags, mode)


def test_every_single_fragment_in_every_form_and_mode():
    """Exhaustive over one-statement bodies, and not vacuous: "unknown for
    everything" would satisfy the two properties, so a floor is set on how
    many resolve. (A one-statement body whose only line is shared with a
    lambda or a nested def is rightly unknown, hence not 100%.)"""
    ran = {"yes": 0, "all": 0}
    idle = {"no": 0, "all": 0}
    for form in FACTORY_FORMS:
        for i in range(len(FRAGMENTS)):
            for mode in FACTORY_MODES:
                got = check_factory(form, [i], mode)
                if form not in ("block", "signature", "decorated"):
                    continue
                if mode == "called":
                    ran["all"] += 1
                    ran["yes"] += got is True
                elif mode == "idle":
                    idle["all"] += 1
                    idle["no"] += got is False
    assert ran["all"] == idle["all"] == 3 * len(FRAGMENTS)
    assert ran["yes"] / ran["all"] >= 0.65, ran
    assert idle["no"] / idle["all"] >= 0.4, idle

    ran = {"yes": 0, "all": 0}
    idle = {"no": 0, "all": 0}
    for form in HANDLER_FORMS:
        for sibling in SIBLINGS:
            for i in range(len(FRAGMENTS)):
                for mode in HANDLER_MODES:
                    got = check_handler(form, sibling, [i], mode)
                    if form not in ("block", "as", "multiline"):
                        continue
                    if mode == "hit":
                        ran["all"] += 1
                        ran["yes"] += got[0] is True
                    elif mode == "miss":
                        idle["all"] += 1
                        idle["no"] += got[0] is False
    assert ran["all"] == idle["all"] == 3 * len(SIBLINGS) * len(FRAGMENTS)
    assert ran["yes"] / ran["all"] >= 0.7, ran
    assert idle["no"] / idle["all"] >= 0.45, idle


def test_plain_bodies_resolve_both_ways():
    plain = [FRAGMENTS.index("x = 1")]
    for form in ("block", "signature", "decorated"):
        assert check_factory(form, plain, "called") is True
        assert check_factory(form, plain, "idle") is False
        assert check_factory(form, plain, "deferred") is False
    for form in ("block", "as", "multiline"):
        assert check_handler(form, "block", plain, "hit") == [True, False]
        assert check_handler(form, "block", plain, "sibling") == [False, True]
        assert check_handler(form, "block", plain, "miss") == [False, False]


def test_a_statement_spread_over_lines_still_counts():
    wrapped = [FRAGMENTS.index("(\n    calls.append(1)\n)")]
    assert check_factory("block", wrapped, "called") is True
    assert check_handler("block", "none", wrapped, "hit") == [True]


def test_body_without_a_line_of_its_own_is_unknown():
    assert check_factory("inline", [0], "called") is None
    assert check_factory("inline", [0], "idle") is None
    # a body on the last line of a spread-out signature has that line to itself
    assert check_factory("signature_inline", [0], "called") is True
    assert check_factory("signature_inline", [0], "idle") is False
    doc = [FRAGMENTS.index('"""doc"""')]
    assert check_factory("block", doc, "called") is None
    assert check_factory("block", doc, "idle") is None
    assert check_handler("inline", "none", [0], "hit") == [None]
    assert check_handler("inline", "none", [0], "miss") == [None]


def test_lambda_default_of_a_nested_helper_does_not_credit_the_enclosing_code():
    helper = [FRAGMENTS.index("def helper(cb=lambda: 1):\n    return cb\nout.append(helper())")]
    assert check_factory("block", helper, "deferred") is not True
    assert check_handler("block", "none", helper, "deferred") != [True]


def test_first_line_that_raises_is_not_read_as_not_run():
    raising = [FRAGMENTS.index("out.append(boom() or (lambda: 1))")]
    assert check_factory("block", raising, "called") is not False


def test_anchor_lines_leave_out_every_shared_line():
    src = (
        "def create_app(xs):\n"          # 1
        "    a = 1\n"                    # 2  only the factory can emit it
        "    g = (x for x in xs)\n"      # 3  shared with the generator
        "    h = lambda: a\n"            # 4  shared with the lambda
        "    def inner():\n"             # 5  shared: inner's own first line
        "        return a\n"             # 6  inner's
        "    def one(): return a\n"      # 7  shared
        "    if a:\n"                    # 8
        "        a = 2\n"                # 9
        "    return inner\n"             # 10
    )
    anchors = _lines.ModuleCode(src).function_anchors(_fn_node(src, "create_app"))
    assert anchors.lines == {2, 8, 9, 10}
    assert anchors.entry == 2


def test_source_that_does_not_compile_has_no_anchor():
    good = "def create_app():\n    return 1\n"
    node = _fn_node(good, "create_app")
    anchors = _lines.ModuleCode("def create_app(:\n").function_anchors(node)
    assert anchors.lines == frozenset() and anchors.entry is None
    assert _lines.judge(anchors, {2: {LABEL}}) == (None, [])


def test_boundary_verdict_three_values():
    assert _failpaths.boundary_verdict([True, None, False]) is True
    assert _failpaths.boundary_verdict([False, False]) is False
    assert _failpaths.boundary_verdict([False, None]) is None
    assert _failpaths.boundary_verdict([None]) is None
