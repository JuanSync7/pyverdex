"""Semantic boundary-category detection (import/AST based).

``evaluate``'s filename heuristic (``_category``) guesses a boundary's category
from substrings in its dotted *module name* — so a handler module that in fact
talks to a database is misread as ``api`` just because it isn't named ``*db*``.
This detector instead reads the module's real source, parses its imports, and
classifies by the frameworks it actually uses, returning ``None`` (so the caller
falls back to the filename heuristic) when the file can't be read or imports no
known framework.

Detection is deliberately import-based and category-only: the lifecycle pattern
still comes from ``evaluate``'s existing category→pattern map. ``file`` is not
detected here — ``open``/``pathlib`` are too ubiquitous to be a reliable import
signal — so it stays with the filename fallback. See ADR 0003.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

# (category, import-name tells) in PRIORITY order: the first category with any
# tell that names (or prefixes) an imported module wins. db/queue are more
# specific boundary kinds than a generic HTTP client, so they outrank api when a
# module touches several — e.g. a repository that imports both sqlalchemy and
# httpx classifies as db. See ADR 0003 for the precedence rationale.
_FRAMEWORK_SIGNS: list[tuple[str, tuple[str, ...]]] = [
    ("db", ("sqlalchemy", "psycopg2", "psycopg", "pymongo", "asyncpg", "sqlite3",
            "django.db", "mysql", "motor", "aiomysql", "aiosqlite", "redis")),
    ("queue", ("celery", "kombu", "pika", "dramatiq", "kafka", "confluent_kafka",
               "aiokafka")),
    ("cli", ("click", "typer", "argparse")),
    ("api", ("fastapi", "flask", "starlette", "requests", "httpx", "aiohttp",
             "boto3", "openai", "urllib3", "grpc")),
]


def _module_file(source_root: Path, dotted: str) -> Optional[Path]:
    """Resolve a dotted module to its source file (``pkg/mod.py`` or, for a
    package, ``pkg/__init__.py``)."""
    base = source_root.joinpath(*dotted.split("."))
    mod = base.with_suffix(".py")
    if mod.is_file():
        return mod
    pkg = base / "__init__.py"
    return pkg if pkg.is_file() else None


def _imported_names(tree: ast.AST) -> set[str]:
    """Absolute module names this source imports, from both ``import a.b`` and
    ``from a.b import c``. Relative imports (``from . import x``) are skipped —
    they name project-local modules, not third-party frameworks."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _matches(imported: set[str], tell: str) -> bool:
    """True when ``tell`` equals an imported module or is a package prefix of one
    (so ``sqlalchemy`` matches ``sqlalchemy.orm`` and ``django.db`` matches
    ``django.db.models``)."""
    return any(name == tell or name.startswith(tell + ".") for name in imported)


def detect_framework(module: str, source_root: Path) -> Optional[str]:
    """Classify a boundary's category from the frameworks its source imports.

    Returns a ``BoundaryCategory`` value (``db``/``queue``/``cli``/``api``) or
    ``None`` when the module file can't be read or imports no known framework —
    the caller then falls back to the filename heuristic.
    """
    path = _module_file(source_root, module)
    if path is None:
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
        return None
    imported = _imported_names(tree)
    for category, tells in _FRAMEWORK_SIGNS:
        if any(_matches(imported, t) for t in tells):
            return category
    return None


__all__ = ["detect_framework"]
