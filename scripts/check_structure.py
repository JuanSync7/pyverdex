#!/usr/bin/env python3
"""
check_structure.py - enforce the project conventions (see CONVENTIONS.md).

pyverdex follows the Project Keel structural standard. This checker is adapted
from Keel's `scripts/check_structure.py` for pyverdex's phased migration: the
labeling / manifest / symlink gates (A, B, H, I) are live now; the code-boundary
gates (C, D, E) activate automatically once the backend lands in `src/backend/`
(refactor phase 2). The gitignored vendored trees under `src/pyverdex/` (the
separate juansync-synapse `tools/vendored` + `knowledge` checkouts) are excluded
- they are not subject to this repo's conventions.

Checks:
  A. Frontmatter validity on README.md / AGENT.md / CLAUDE.md and docs/** *.md
  B. Each taxonomy directory that exists has README.md + CLAUDE.md
  C. Each src/ directory containing *.py is a package: __init__.py with __all__
     (staged: runs once src/backend/ exists)
  D. The __init__ boundary: no absolute import of another package's _private
     module (staged: runs once src/backend/ exists)
  E. Authored coverage (WARN): every __all__-exported symbol has a docstring
     (staged: runs once src/backend/ exists)
  H. Project facts in config/project.json agree with the tree (ERR); an
     undeclared leftover stack/transport dir WARNs (CONVENTIONS section 15).
     An optional 'runtimes' block is validated the same way (section 16).
  I. Agent-rules symlink (ERR): every CLAUDE.md is a symlink to its sibling
     AGENT.md, and every AGENT.md has that sibling (CONVENTIONS section 5).

Exit 0 = clean, 1 = errors. Warnings never fail the build. Stdlib only; 3.6+.
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".astro", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    # vendored juansync-synapse checkouts (gitignored, not our conventions)
    "vendored", "knowledge",
}

KINDS = {
    "readme", "rules", "package", "module", "tests", "test-doc", "doc", "spec",
    "design", "adr", "config", "script", "agent", "mcp", "api", "wiki", "demo",
    "model", "eval", "container", "ops", "tool",
}
LAYERS = {"frontend", "backend", "shared", "app", "cross-cutting", "n/a"}
STATUSES = {
    "draft", "stable", "deprecated", "template",
    "proposed", "accepted", "superseded",
}
VISIBILITIES = {"public", "internal", "confidential", "restricted"}
REQUIRED_KEYS = ("title", "kind", "layer", "status", "summary",
                 "id", "created", "updated", "visibility", "canonical")

TAXONOMY = [
    "src", "tests", "test-docs", "docs", "agents", "mcp", "api", "wiki",
    "scripts", "config", "demo", "containers", "evals", "ops", "models",
    "runtimes",
]
REQUIRED_TOPLEVEL = ["src", "tests", "docs"]
CODE_ROOTS = ["src", "tests", "api", "models", "mcp", "agents", "demo",
              "scripts", "runtimes"]

errors = []
warnings = []
notes = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def rel(p):
    return os.path.relpath(p, ROOT)


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        yield dirpath, dirnames, filenames


def _backend_migrated():
    """The code-boundary checks (C/D/E) activate once the backend has moved
    into src/backend/ (refactor phase 2). Until then they would only police
    code that is about to move, so they are staged off."""
    return os.path.isdir(os.path.join(ROOT, "src", "backend"))


def parse_frontmatter(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except Exception as e:
        err("%s: cannot read (%s)" % (rel(path), e))
        return {}
    if not text.startswith("---"):
        return None
    data = {}
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            return data
        if line[:1] in (" ", "\t"):
            continue  # nested key - not top-level
        if ":" in line:
            k, _, v = line.partition(":")
            data[k.strip()] = v.strip()
    return None  # block never closed


def check_frontmatter(path, seen_ids):
    fm = parse_frontmatter(path)
    if fm is None:
        err("%s: missing or unterminated frontmatter block" % rel(path))
        return
    for k in REQUIRED_KEYS:
        if not fm.get(k):
            err("%s: frontmatter missing required key '%s'" % (rel(path), k))
    if fm.get("kind") and fm["kind"] not in KINDS:
        err("%s: invalid kind '%s'" % (rel(path), fm["kind"]))
    if fm.get("layer") and fm["layer"] not in LAYERS:
        err("%s: invalid layer '%s'" % (rel(path), fm["layer"]))
    if fm.get("status") and fm["status"] not in STATUSES:
        err("%s: invalid status '%s'" % (rel(path), fm["status"]))
    if fm.get("visibility") and fm["visibility"] not in VISIBILITIES:
        err("%s: invalid visibility '%s'" % (rel(path), fm["visibility"]))
    fid = fm.get("id")
    if fid:
        if fid in seen_ids:
            err("%s: duplicate id '%s' (also in %s)"
                % (rel(path), fid, seen_ids[fid]))
        else:
            seen_ids[fid] = rel(path)
    can = fm.get("canonical")
    if can and can not in ("true", "false", "self"):
        if ("/" in can or can.endswith(".md")) and \
                not os.path.exists(os.path.join(ROOT, can)):
            err("%s: canonical target '%s' does not exist" % (rel(path), can))
    if fm.get("status") == "deprecated" and not fm.get("superseded_by"):
        err("%s: status is 'deprecated' but no 'superseded_by' is set" % rel(path))
    if not fm.get("owner"):
        warn("%s: frontmatter missing 'owner'" % rel(path))


def check_A():
    seen_ids = {}
    seen_real = set()  # dedupe symlink + target (CLAUDE.md -> AGENT.md)
    for dirpath, _, filenames in walk(ROOT):
        top = rel(dirpath).split(os.sep)[0]
        in_docs = top in ("docs", "test-docs")
        for f in filenames:
            if f in ("README.md", "AGENT.md", "CLAUDE.md") \
                    or (in_docs and f.endswith(".md")):
                full = os.path.join(dirpath, f)
                real = os.path.realpath(full)
                if real in seen_real:
                    continue
                seen_real.add(real)
                check_frontmatter(full, seen_ids)


def check_B():
    for d in REQUIRED_TOPLEVEL:
        if not os.path.isdir(os.path.join(ROOT, d)):
            err("required top-level dir '%s/' is missing" % d)
    for d in TAXONOMY:
        full = os.path.join(ROOT, d)
        if os.path.isdir(full):
            for need in ("README.md", "CLAUDE.md"):
                if not os.path.isfile(os.path.join(full, need)):
                    err("%s/: missing %s" % (d, need))


def check_C():
    if not _backend_migrated():
        notes.append("check_C/D/E staged off (src/backend/ not present yet)")
        return
    srcroot = os.path.join(ROOT, "src")
    for dirpath, _, filenames in walk(srcroot):
        if not any(f.endswith(".py") for f in filenames):
            continue
        if "__init__.py" not in filenames:
            err("%s/: has .py files but no __init__.py (package boundary)"
                % rel(dirpath))
            continue
        init = os.path.join(dirpath, "__init__.py")
        try:
            with open(init, encoding="utf-8") as fh:
                if "__all__" not in fh.read():
                    err("%s: __init__.py defines no __all__ (public API surface)"
                        % rel(init))
        except Exception as e:
            err("%s: cannot read (%s)" % (rel(init), e))


def _private_segment(dotted):
    if not dotted:
        return False
    for part in dotted.split("."):
        if part.startswith("_") and not part.startswith("__"):
            return True
    return False


def check_D():
    if not _backend_migrated():
        return
    for croot in CODE_ROOTS:
        base = os.path.join(ROOT, croot)
        if not os.path.isdir(base):
            continue
        for dirpath, _, filenames in walk(base):
            for f in filenames:
                if not f.endswith(".py"):
                    continue
                full = os.path.join(dirpath, f)
                try:
                    with open(full, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read(), filename=full)
                except Exception as e:
                    warn("%s: could not parse (%s)" % (rel(full), e))
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.level == 0 and _private_segment(node.module):
                            err("%s:%d: absolute import of private module '%s' "
                                "crosses a package boundary"
                                % (rel(full), node.lineno, node.module))
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if _private_segment(alias.name):
                                err("%s:%d: import of private module '%s' "
                                    "crosses a package boundary"
                                    % (rel(full), node.lineno, alias.name))


def _exported_names(tree):
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__" \
                        and isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        val = getattr(elt, "s", None)
                        if val is None and isinstance(elt, ast.Constant):
                            val = elt.value
                        if isinstance(val, str):
                            out.append(val)
    return out


def check_E():
    if not _backend_migrated():
        return
    for croot in CODE_ROOTS:
        base = os.path.join(ROOT, croot)
        if not os.path.isdir(base):
            continue
        for dirpath, _, filenames in walk(base):
            for f in filenames:
                if not f.endswith(".py"):
                    continue
                full = os.path.join(dirpath, f)
                try:
                    with open(full, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read(), filename=full)
                except Exception:
                    continue
                exported = _exported_names(tree)
                if not exported:
                    continue
                defs = {}
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef)):
                        defs[node.name] = node
                for name in sorted(exported):
                    nd = defs.get(name)
                    if nd is not None and not ast.get_docstring(nd):
                        warn("%s: exported symbol '%s' has no docstring"
                             % (rel(full), name))


def _requires_python():
    try:
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return None
    m = re.search(r'requires-python\s*=\s*(["\'])([^"\']+)\1', text)
    return m.group(2).strip() if m else None


def _subdirs(relpath):
    base = os.path.join(ROOT, relpath)
    out = []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if name not in IGNORE_DIRS and os.path.isdir(os.path.join(base, name)):
                out.append(name)
    return out


def _expect(val, typ, label, default):
    if val is None:
        return default
    if not isinstance(val, typ):
        want = "a list" if typ is list else "an object" if typ is dict else typ.__name__
        err("config/project.json: %s must be %s" % (label, want))
        return default
    return val


def check_H():
    path = os.path.join(ROOT, "config", "project.json")
    if not os.path.isfile(path):
        warn("config/project.json: not found; project facts are unenforced")
        return
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as e:
        err("config/project.json: invalid JSON (%s)" % e)
        return
    if not isinstance(manifest, dict):
        err("config/project.json: top level must be a JSON object")
        return
    layers = _expect(manifest.get("layers"), dict, "layers", {})

    backend = _expect(layers.get("backend"), dict, "layers.backend", {})
    bpath = backend.get("path")
    if isinstance(bpath, str) and bpath and not os.path.isdir(os.path.join(ROOT, bpath)):
        err("config/project.json: layers.backend.path '%s' does not exist" % bpath)
    bpy = backend.get("python")
    if isinstance(bpy, str) and bpy:
        have = _requires_python()
        if have is not None and have != bpy:
            err("config/project.json: layers.backend.python '%s' != pyproject "
                "requires-python '%s'" % (bpy, have))

    frontend = _expect(layers.get("frontend"), dict, "layers.frontend", {})
    froot = frontend.get("root")
    if isinstance(froot, str) and froot:
        available = _expect(frontend.get("available"), list,
                            "layers.frontend.available", [])
        stack = frontend.get("stack")
        if isinstance(stack, str) and stack \
                and not os.path.isdir(os.path.join(ROOT, froot, stack)):
            err("config/project.json: layers.frontend.stack '%s' has no dir "
                "under %s/" % (stack, froot))
        for a in available:
            if isinstance(a, str) and not os.path.isdir(os.path.join(ROOT, froot, a)):
                warn("config/project.json: declared frontend stack '%s' is "
                     "missing (%s/%s)" % (a, froot, a))

    transports = _expect(manifest.get("transports"), dict, "transports", {})
    enabled = _expect(transports.get("enabled"), list, "transports.enabled", [])
    avail = _expect(transports.get("available"), dict, "transports.available", {})
    for t in enabled:
        if t not in avail:
            err("config/project.json: transports.enabled '%s' not in "
                "transports.available" % t)
        elif isinstance(avail[t], str) \
                and not os.path.isdir(os.path.join(ROOT, avail[t])):
            err("config/project.json: enabled transport '%s' -> '%s' does not "
                "exist" % (t, avail[t]))
    declared = set(v for v in avail.values() if isinstance(v, str))
    for d in _subdirs("api"):
        if os.path.join("api", d) not in declared:
            warn("api/%s: present but not in config/project.json "
                 "transports.available (undeclared transport)" % d)

    runtimes = manifest.get("runtimes")
    if runtimes is not None:
        runtimes = _expect(runtimes, dict, "runtimes", {})
        r_avail = _expect(runtimes.get("available"), dict, "runtimes.available", {})
        r_default = runtimes.get("default")
        if r_default is not None and r_default not in r_avail:
            err("config/project.json: runtimes.default '%s' not in "
                "runtimes.available" % r_default)
        for nm in sorted(r_avail):
            d = r_avail[nm]
            if isinstance(d, str) and not os.path.isdir(os.path.join(ROOT, d)):
                err("config/project.json: runtime '%s' -> '%s' does not exist"
                    % (nm, d))


def check_I():
    for dirpath, _, filenames in walk(ROOT):
        has_agent = "AGENT.md" in filenames
        if "CLAUDE.md" in filenames:
            claude = os.path.join(dirpath, "CLAUDE.md")
            if not os.path.islink(claude):
                err("%s: must be a symlink to the sibling AGENT.md, not a "
                    "regular file (CONVENTIONS section 5)" % rel(claude))
            elif os.readlink(claude) != "AGENT.md":
                err("%s: symlink target '%s' must be exactly 'AGENT.md'"
                    % (rel(claude), os.readlink(claude)))
            elif not os.path.isfile(os.path.join(dirpath, "AGENT.md")):
                err("%s: symlink target AGENT.md does not exist" % rel(claude))
        elif has_agent:
            err("%s/AGENT.md: has no sibling CLAUDE.md symlink "
                "(CONVENTIONS section 5)" % rel(dirpath))


def main():
    check_A()
    check_B()
    check_C()
    check_D()
    check_E()
    check_H()
    check_I()
    for n_ in notes:
        print("NOTE  " + n_)
    for w_ in warnings:
        print("WARN  " + w_)
    for e_ in errors:
        print("ERROR " + e_)
    print("")
    print("check_structure: %d error(s), %d warning(s)"
          % (len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
