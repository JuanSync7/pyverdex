"""Phase F — function-to-function call-edge coverage.

Denominator = statically-resolvable internal call edges (caller fn -> callee
top-level fn in the source tree); numerator = call-site-covered (an edge is
exercised iff any of its call-site lines executed).
"""

from __future__ import annotations

from pathlib import Path

from pyverdex.skills._edges import (
    build_function_edges,
    compute_edge_coverage,
    edge_coverage,
)


def _src(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "src"
    for dotted, code in files.items():
        f = root.joinpath(*dotted.split(".")).with_suffix(".py")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code, encoding="utf-8")
    return root


def _edge_keys(edges):
    return {
        (e["caller_module"], e["caller_function"], e["callee_module"], e["callee_function"])
        for e in edges
    }


# --- static extraction: which edges are (and aren't) resolvable -------------

def test_intra_module_edge(tmp_path):
    root = _src(tmp_path, {"m": "def helper():\n    return 1\n\ndef top():\n    return helper()\n"})
    edges = build_function_edges(root)
    assert ("m", "top", "m", "helper") in _edge_keys(edges)


def test_from_import_edge(tmp_path):
    root = _src(tmp_path, {
        "util": "def calc():\n    return 2\n",
        "app": "from util import calc\n\ndef run():\n    return calc()\n",
    })
    assert ("app", "run", "util", "calc") in _edge_keys(build_function_edges(root))


def test_module_alias_attribute_edge(tmp_path):
    root = _src(tmp_path, {
        "util": "def calc():\n    return 2\n",
        "app": "import util as u\n\ndef run():\n    return u.calc()\n",
    })
    assert ("app", "run", "util", "calc") in _edge_keys(build_function_edges(root))


def test_from_import_of_package_function_via_init(tmp_path):
    root = _src(tmp_path, {
        "pkg.__init__": "def boot():\n    return 1\n",
        "app": "from pkg import boot\n\ndef run():\n    return boot()\n",
    })
    # __init__ collapses to the package name 'pkg' so the import resolves
    assert ("app", "run", "pkg", "boot") in _edge_keys(build_function_edges(root))


def test_qualified_caller_for_method(tmp_path):
    root = _src(tmp_path, {
        "m": "def helper():\n    return 1\n\nclass C:\n    def method(self):\n        return helper()\n",
    })
    assert ("m", "C.method", "m", "helper") in _edge_keys(build_function_edges(root))


def test_external_and_unresolved_calls_are_not_edges(tmp_path):
    # stdlib call, builtin, and a method call on an object -> none are internal edges
    root = _src(tmp_path, {
        "m": "import os\n\ndef top(x):\n    print(len(x))\n    os.getcwd()\n    return x.upper()\n",
    })
    assert build_function_edges(root) == []


def test_call_sites_are_aggregated_and_deduped(tmp_path):
    root = _src(tmp_path, {
        "m": "def helper():\n    return 1\n\ndef top():\n    helper()\n    return helper()\n",
    })
    edges = build_function_edges(root)
    edge = next(e for e in edges if e["callee_function"] == "helper")
    assert edge["call_sites"] == [5, 6]  # both call sites, one edge


def test_syntax_error_file_is_skipped(tmp_path):
    root = _src(tmp_path, {"ok": "def f():\n    return 1\n", "bad": "def (:\n"})
    edges = build_function_edges(root)  # must not raise
    assert all(e["caller_module"] != "bad" for e in edges)


# --- numerator: call-site-covered -------------------------------------------

def test_compute_edge_coverage_call_site_covered():
    edges = [
        {"caller_module": "m", "caller_function": "a", "callee_module": "m",
         "callee_function": "b", "call_sites": [10]},
        {"caller_module": "m", "caller_function": "c", "callee_module": "m",
         "callee_function": "d", "call_sites": [20]},
    ]
    executed = {"m": {10}}  # only the first call site ran
    cov = compute_edge_coverage(edges, executed)
    assert cov["total"] == 2
    assert cov["exercised"] == 1
    assert cov["pct"] == 50.0
    assert cov["uncovered_total"] == 1
    assert cov["uncovered"][0]["caller_function"] == "c"


def test_compute_edge_coverage_any_call_site_counts():
    edges = [{"caller_module": "m", "caller_function": "a", "callee_module": "m",
              "callee_function": "b", "call_sites": [5, 6]}]
    assert compute_edge_coverage(edges, {"m": {6}})["exercised"] == 1  # 2nd site ran


def test_compute_edge_coverage_empty_is_full():
    cov = compute_edge_coverage([], {})
    assert cov["total"] == 0 and cov["pct"] == 100.0


# --- orchestration: graceful degradation without .coverage ------------------

def test_edge_coverage_without_coverage_data(tmp_path):
    root = _src(tmp_path, {"m": "def helper():\n    return 1\n\ndef top():\n    return helper()\n"})
    ec = edge_coverage(tmp_path, root)  # no .coverage file in tmp_path
    assert ec["have_coverage"] is False
    assert ec["pct"] is None and ec["exercised"] is None
    assert ec["total"] == 1  # the map is still reported


def test_edge_coverage_end_to_end_with_real_coverage(tmp_path):
    """Run coverage.py for real over a tiny package and assert the exercised
    edge is counted and the never-called edge is not."""
    coverage_lib = __import__("coverage")
    root = _src(tmp_path, {
        "m": (
            "def used():\n    return 1\n\n"
            "def unused():\n    return 2\n\n"
            "def top():\n    return used()\n"  # calls used(), never unused()
        ),
    })
    cov = coverage_lib.Coverage(data_file=str(tmp_path / ".coverage"))
    cov.start()
    import sys
    sys.path.insert(0, str(root))
    try:
        import m  # noqa
        m.top()
    finally:
        cov.stop()
        cov.save()
        sys.path.remove(str(root))
        sys.modules.pop("m", None)

    ec = edge_coverage(tmp_path, root)
    assert ec["have_coverage"] is True
    # only edge is top->used, and its call site executed
    assert ec["total"] == 1 and ec["exercised"] == 1 and ec["pct"] == 100.0
