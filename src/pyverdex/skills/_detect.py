"""Semantic boundary detection (import/AST based).

``evaluate``'s filename heuristic (``_category``) guesses a boundary's category
from substrings in its dotted *module name* — so a handler module that in fact
talks to a database is misread as ``api`` just because it isn't named ``*db*``.
This detector instead reads the module's real source, parses its imports, and
classifies by the frameworks it actually uses, returning ``None`` (so the caller
falls back to the filename heuristic) when the file can't be read or imports no
known framework.

It resolves both a **category** (from the imported frameworks) and a **lifecycle
pattern**: the category's default, refined per-framework where the source gives a
stronger signal — a db module that executes DDL (``create_all``/``drop_all`` or an
alembic import) needs a fresh schema per test (``schema-per-test``) rather than a
transaction rollback; a temporal module needs a ``workflow-environment``. Pattern
overrides are category-scoped, so the pattern never disagrees with the category.
``file`` is not detected here
(``open``/``pathlib`` are too ubiquitous to be a reliable import signal), so it
stays with the filename fallback. See ADR 0003.
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
               "aiokafka", "temporalio")),
    ("cli", ("click", "typer", "argparse")),
    ("api", ("fastapi", "flask", "starlette", "requests", "httpx", "aiohttp",
             "boto3", "openai", "urllib3", "grpc")),
]

# Canonical category → default lifecycle pattern (LifecyclePattern enum values).
# Single source of truth: evaluate imports this for its filename-fallback path.
CATEGORY_PATTERN: dict[str, str] = {
    "db": "transaction-rollback", "api": "vcrpy", "queue": "celery-test-harness",
    "file": "tmp_path", "cli": "subprocess-capture",
}

# Per-category pattern refinements, applied ONLY when that category won precedence
# — so the pattern can never disagree with the category (a module importing both
# sqlalchemy and temporalio is a db boundary, not a workflow). Each override is a
# source-side signal: what the boundary itself does. category -> [(tells, pattern)].
_PATTERN_OVERRIDES: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "queue": [(("temporalio",), "workflow-environment")],
}

# AST signal that a db module *executes* schema DDL (and so needs a fresh schema
# per test, not a transaction rollback): a create_all/drop_all call, or an alembic
# (migrations) import. Bare MetaData/Table construction is schema *definition*,
# not creation, and a bare name is too easily shadowed — so it does not count.
_DDL_ATTRS = {"create_all", "drop_all"}


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


def _uses_ddl(imported: set[str], tree: ast.AST) -> bool:
    """True when the module executes schema DDL: an alembic (migrations) import,
    or a create_all/drop_all call."""
    if _matches(imported, "alembic"):
        return True
    return any(isinstance(node, ast.Attribute) and node.attr in _DDL_ATTRS
               for node in ast.walk(tree))


def _pattern_for(category: str, imported: set[str], tree: ast.AST) -> str:
    """The lifecycle pattern for a detected category, refined per-framework. Only
    the winning category's own overrides apply, so pattern and category agree."""
    for tells, pattern in _PATTERN_OVERRIDES.get(category, []):
        if any(_matches(imported, t) for t in tells):
            return pattern
    if category == "db" and _uses_ddl(imported, tree):
        return "schema-per-test"
    return CATEGORY_PATTERN[category]


def detect_boundary(module: str, source_root: Path) -> Optional[tuple[str, str]]:
    """Classify a boundary from the frameworks its source imports.

    Returns ``(category, lifecycle_pattern)`` — both valid ``BoundaryCategory`` /
    ``LifecyclePattern`` enum values — or ``None`` when the module file can't be
    read or imports no known framework (the caller then falls back to the
    filename heuristic).
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
            return category, _pattern_for(category, imported, tree)
    return None


def detect_framework(module: str, source_root: Path) -> Optional[str]:
    """Category-only view of :func:`detect_boundary` (``db``/``queue``/``cli``/
    ``api`` or ``None``)."""
    detected = detect_boundary(module, source_root)
    return detected[0] if detected else None


__all__ = ["detect_boundary", "detect_framework", "CATEGORY_PATTERN"]
