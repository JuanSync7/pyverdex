from __future__ import annotations

from pathlib import Path

from pyverify.discovery import detect_source_root, detect_test_root, discover_config, project_info

REPO = Path(__file__).resolve().parents[1]


def test_src_layout_detection():
    cfg = discover_config(REPO / "examples" / "sample_project")
    assert cfg.paths.source_root == "src"
    assert cfg.paths.test_root == "tests"
    info = project_info(cfg)
    assert info["source_count"] >= 1
    assert info["test_count"] == 1


def test_flat_layout(tmp_path: Path):
    (tmp_path / "mod.py").write_text("def f(x):\n    return x + 1\n")
    (tmp_path / "test_mod.py").write_text("from mod import f\n\ndef test_f():\n    assert f(1) == 2\n")
    assert detect_test_root(tmp_path) == "."
    assert detect_source_root(tmp_path, ".") == "."
    cfg = discover_config(tmp_path)
    assert cfg.paths.source_root == "."


def test_pyverify_yaml_is_respected():
    cfg = discover_config(REPO / "demo" / "sample_app")
    # .pyverify.yaml pins line_standard to 80 and max_cycles to 2
    assert cfg.thresholds.line_standard == 80.0
    assert cfg.loop.max_cycles == 2


def test_demo_has_boundary_and_gaps():
    cfg = discover_config(REPO / "demo" / "sample_app")
    info = project_info(cfg)
    assert info["source_root"] == "src"
    assert info["test_count"] == 2
