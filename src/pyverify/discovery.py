"""Generic adapter: point pyverify at any pytest project and get a Config.

Resolution order for a target directory:

1. ``.pyverify.yaml`` in the project root  → load it (explicit).
2. ``[tool.pyverify]`` table in ``pyproject.toml``  → use it (explicit).
3. Auto-detect source/test layout (src-layout, single top-level package, or
   flat) by inspecting the tree.

``project_info`` enumerates the source and test files so a UI can show
"all the tests and source code" and the detected wiring.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

from .config import Config

_IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "node_modules", "build", "dist", ".eggs", "project", "site-packages",
}


def _iter_py(root: Path):
    for p in root.rglob("*.py"):
        if any(part in _IGNORE_DIRS or part.endswith(".egg-info") for part in p.parts):
            continue
        yield p


def detect_test_root(root: Path) -> str:
    for name in ("tests", "test"):
        if (root / name).is_dir():
            return name
    # fall back to the shallowest dir that holds test_*.py / *_test.py
    candidates = {
        p.parent.relative_to(root)
        for p in _iter_py(root)
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    }
    if candidates:
        best = min(candidates, key=lambda c: len(c.parts))
        return str(best) if str(best) != "." else "."
    return "."


def detect_source_root(root: Path, test_root: str) -> str:
    if (root / "src").is_dir():
        return "src"
    # a single top-level importable package (has __init__.py), excluding tests
    pkgs = [
        d.name for d in root.iterdir()
        if d.is_dir() and d.name not in _IGNORE_DIRS
        and d.name not in {test_root, "tests", "test"}
        and (d / "__init__.py").exists()
    ]
    if len(pkgs) == 1:
        return pkgs[0]
    return "."


def _pyproject_overrides(root: Path) -> dict[str, Any]:
    pp = root / "pyproject.toml"
    if not pp.exists():
        return {}
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    return data.get("tool", {}).get("pyverify", {}) or {}


def discover_config(path: str | Path, **overrides: Any) -> Config:
    root = Path(path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    data: dict[str, Any] = {}
    yaml_path = root / ".pyverify.yaml"
    if yaml_path.exists():
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    elif _pyproject_overrides(root):
        data = _pyproject_overrides(root)

    cfg = Config(**data)
    cfg.project_root = str(root)
    # only auto-detect paths the config did not pin
    if "paths" not in data or "test_root" not in (data.get("paths") or {}):
        cfg.paths.test_root = detect_test_root(root)
    if "paths" not in data or "source_root" not in (data.get("paths") or {}):
        cfg.paths.source_root = detect_source_root(root, cfg.paths.test_root)

    for key, value in overrides.items():
        if value is not None:
            setattr(cfg, key, value)
    return cfg


def project_info(cfg: Config) -> dict[str, Any]:
    """Enumerate detected wiring + source/test files (relative to project root)."""
    root = cfg.root
    src = cfg.abs_source_root
    test = cfg.abs_test_root

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(root))
        except ValueError:
            return str(p)

    source_files = sorted(_rel(p) for p in _iter_py(src)) if src.is_dir() else []
    test_files = sorted(
        _rel(p) for p in (_iter_py(test) if test.is_dir() else [])
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    )
    return {
        "project_root": str(root),
        "source_root": cfg.paths.source_root,
        "test_root": cfg.paths.test_root,
        "source_files": source_files,
        "test_files": test_files,
        "source_count": len(source_files),
        "test_count": len(test_files),
        "has_tests": bool(test_files),
    }


__all__ = ["discover_config", "detect_source_root", "detect_test_root", "project_info"]
