"""Dependency declaration checks: undeclared imports, unpinned versions, lockfiles."""
from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from ..model import Finding, Project
from . import register

# Import name -> distribution name, where they differ.
IMPORT_TO_DIST = {
    "yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv-python", "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "jwt": "pyjwt", "serial": "pyserial", "usb": "pyusb", "OpenSSL": "pyopenssl",
    "attr": "attrs", "google": "google-api-python-client", "pkg_resources": "setuptools",
    "setuptools": "setuptools", "win32com": "pywin32", "docx": "python-docx",
    "pptx": "python-pptx", "fitz": "pymupdf", "Crypto": "pycryptodome",
    "magic": "python-magic", "redis": "redis", "psycopg2": "psycopg2-binary",
    "zoneinfo": "", "tomllib": "",
}

REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")
PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([<>=!~^].*)?$")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def stdlib_names() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", ()))
    names |= {
        "os", "sys", "re", "json", "math", "time", "typing", "pathlib", "dataclasses",
        "collections", "itertools", "functools", "subprocess", "argparse", "logging",
        "unittest", "sqlite3", "urllib", "http", "asyncio", "shutil", "tempfile",
        "hashlib", "base64", "datetime", "random", "textwrap", "traceback", "enum",
        "abc", "io", "csv", "glob", "pickle", "socket", "ssl", "threading", "queue",
        "concurrent", "contextlib", "copy", "string", "struct", "uuid", "warnings",
        "zipfile", "tarfile", "platform", "signal", "statistics", "secrets", "ast",
        "inspect", "importlib", "types", "operator", "difflib", "html", "xml", "email",
        "webbrowser", "shlex", "fnmatch", "getpass", "tomllib", "zoneinfo", "gzip",
    }
    return names


def parse_pyproject_deps(text: str) -> tuple[set[str], list[tuple[str, str]]]:
    """Return (normalized names, [(raw_spec, name)]) from a pyproject.toml."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py<3.11
        tomllib = None
    specs: list[str] = []
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception:
            data = {}
        proj = data.get("project") or {}
        specs += [s for s in proj.get("dependencies", []) if isinstance(s, str)]
        for group in (proj.get("optional-dependencies") or {}).values():
            specs += [s for s in group if isinstance(s, str)]
        poetry = ((data.get("tool") or {}).get("poetry") or {})
        for key in ("dependencies", "dev-dependencies"):
            for k in (poetry.get(key) or {}):
                if k.lower() != "python":
                    specs.append(str(k))
        for group in ((poetry.get("group") or {}).values()):
            for k in (group.get("dependencies") or {}):
                if k.lower() != "python":
                    specs.append(str(k))
        for group in (data.get("dependency-groups") or {}).values():
            specs += [s for s in group if isinstance(s, str)]
    else:  # crude fallback
        for m in re.finditer(r'"([A-Za-z0-9][A-Za-z0-9._-]*[^"]*)"', text):
            specs.append(m.group(1))
    out: list[tuple[str, str]] = []
    names: set[str] = set()
    for spec in specs:
        m = PEP508.match(spec.split(";")[0])
        if m:
            names.add(normalize(m.group(1)))
            out.append((spec, normalize(m.group(1))))
    return names, out


def parse_requirements(text: str) -> list[tuple[int, str, str]]:
    """Return [(lineno, name, rest)] for each requirement line."""
    rows = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        line = line.split(";")[0].strip()
        m = REQ_LINE.match(line)
        if m:
            rows.append((i, normalize(m.group(1)), (m.group(3) or "").strip()))
    return rows


# Imports in these trees belong to docs builds, sample apps and benchmarks, and
# are declared (if at all) in their own requirement files.
# Trees that hold documentation builds, tutorial snippets, sample apps and
# benchmarks. Their imports and their fake credentials are not production code.
AUXILIARY_DIR = re.compile(
    r"(?i)^(docs?|docs?[-_]src|src[-_]docs?|examples?|samples?|tutorials?|demos?"
    r"|benchmarks?|scripts|tools|bin|website|site)/"
)


def in_auxiliary_tree(rel_path: str) -> bool:
    """True for documentation, example, benchmark and tooling directories."""
    return bool(AUXILIARY_DIR.match(rel_path))

# Build-time and always-available tooling, never a runtime dependency to declare.
EXEMPT_IMPORTS = {"setuptools", "pkg_resources", "distutils", "wheel", "hatchling",
                  "poetry", "pip", "conftest", "setup"}


def _is_optional_import(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """True if the import is guarded, type-only, or lazily done inside a function.

    A module-level import is a hard requirement. An import nested in a function
    body, wrapped in try/except, or placed under `if TYPE_CHECKING:` is how
    projects declare optional backends and extras, so it is not reported.
    """
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True  # lazy import, typically an optional backend
        if isinstance(cur, ast.Try) and cur.handlers:
            return True  # a guarded import is optional by construction
        if isinstance(cur, ast.If):
            test = ast.dump(cur.test)
            if "TYPE_CHECKING" in test:
                return True
        cur = parents.get(id(cur))
    return False


def top_level_imports(project: Project) -> dict[str, tuple[str, int]]:
    """Map top-level imported module -> (first file, line), for real runtime imports."""
    found: dict[str, tuple[str, int]] = {}
    local = local_module_names(project)
    for path in project.python_files():
        rel = project.rel(path)
        if in_auxiliary_tree(rel) or "/site-packages/" in rel:
            continue
        if path.name in ("setup.py", "conftest.py", "noxfile.py", "tasks.py"):
            continue
        src = project.read(path)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        parents: dict[int, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[id(child)] = parent
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and _is_optional_import(node, parents):
                continue
            mod = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod and mod not in local and mod not in found:
                        found[mod] = (project.rel(path), node.lineno)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import
                    continue
                mod = (node.module or "").split(".")[0]
                if mod and mod not in local and mod not in found:
                    found[mod] = (project.rel(path), node.lineno)
    return found


def local_module_names(project: Project) -> set[str]:
    """Names that resolve inside the repo: modules, packages and fixture directories."""
    names: set[str] = set()
    for p in project.files():
        rel = Path(project.rel(p))
        names.update(part for part in rel.parts[:-1])
    for p in project.python_files():
        rel = Path(project.rel(p))
        parts = rel.parts
        names.add(rel.stem)
        if parts:
            names.add(parts[0])
            if parts[0] in ("src", "lib", "tests", "test") and len(parts) > 1:
                names.add(parts[1])
        if p.name == "__init__.py":
            names.add(p.parent.name)
    return {n for n in names if n}


def declared_python_deps(project: Project) -> tuple[set[str], list[str]]:
    """Union of declared dependency names, plus the files they came from."""
    names: set[str] = set()
    sources: list[str] = []
    pyproject = project.read_name("pyproject.toml")
    if pyproject is not None:
        n, _ = parse_pyproject_deps(pyproject)
        names |= n
        sources.append("pyproject.toml")
    for p in project.files():
        rel = project.rel(p)
        if re.fullmatch(r"(requirements[\w.-]*\.txt|requirements/[\w.-]+\.txt)", rel):
            text = project.read(p) or ""
            names |= {n for _, n, _ in parse_requirements(text)}
            sources.append(rel)
    setup_py = project.read_name("setup.py")
    if setup_py:
        for m in re.finditer(r'["\']([A-Za-z0-9][A-Za-z0-9._-]{1,})\s*(?:[<>=!~][^"\']*)?["\']', setup_py):
            names.add(normalize(m.group(1)))
        sources.append("setup.py")
    cfg = project.read_name("setup.cfg")
    if cfg:
        block = re.search(r"install_requires\s*=\s*(.+?)(?:\n\w|\n\[|\Z)", cfg, re.S)
        if block:
            for line in block.group(1).splitlines():
                m = PEP508.match(line.strip())
                if m:
                    names.add(normalize(m.group(1)))
        sources.append("setup.cfg")
    return names, sources


REQ_FILE = re.compile(r"(requirements[\w.-]*\.txt|requirements/[\w.-]+\.txt)")


def _check_undeclared(project: Project, declared: set[str], sources: list[str]) -> Iterable[Finding]:
    std = stdlib_names()
    for mod, (path, line) in sorted(top_level_imports(project).items()):
        if mod in std or mod in EXEMPT_IMPORTS or mod.startswith("_"):
            continue
        dist = IMPORT_TO_DIST.get(mod, mod)
        if not dist:
            continue
        if normalize(dist) in declared or normalize(mod) in declared:
            continue
        in_tests = path.startswith(("tests/", "test/")) or "/tests/" in path
        yield Finding(
            "deps.undeclared", "medium" if in_tests else "high",
            f"Imported but not declared: {mod}",
            f"`import {mod}` is used but `{dist}` is not in {', '.join(sources)}. "
            "A fresh clone will fail at import time.",
            path=path, line=line,
            fix=f"Add `{dist}` to your dependency list, or vendor/remove the import.",
        )


def _check_pins(project: Project) -> Iterable[Finding]:
    for p in project.files():
        rel = project.rel(p)
        if not REQ_FILE.fullmatch(rel):
            continue
        for lineno, name, rest in parse_requirements(project.read(p) or ""):
            if not rest:
                yield Finding(
                    "deps.unpinned", "medium", f"Unpinned requirement: {name}",
                    "No version specifier, so builds are not reproducible and a "
                    "breaking upstream release can break CI without any commit.",
                    path=rel, line=lineno,
                    fix=f"Pin it, e.g. `{name}>=1.2,<2.0` or `{name}==1.2.3`.",
                )
            elif rest.startswith(">=") and "<" not in rest and "," not in rest:
                yield Finding(
                    "deps.no-upper-bound", "low", f"No upper bound: {name}{rest}",
                    "A major release upstream will be installed automatically.",
                    path=rel, line=lineno,
                    fix=f"Add an upper bound, e.g. `{name}{rest},<{_next_major(rest)}`.",
                )


def _check_python(project: Project) -> Iterable[Finding]:
    py_files = project.python_files()
    if not py_files:
        return
    declared, sources = declared_python_deps(project)
    if not sources:
        yield Finding(
            "deps.no-manifest", "high", "No Python dependency manifest",
            f"{len(py_files)} Python files but no pyproject.toml, requirements.txt, "
            "setup.py or setup.cfg declaring dependencies.",
            fix="Create a pyproject.toml with a [project] table and a dependencies list.",
        )
    else:
        yield from _check_undeclared(project, declared, sources)
    yield from _check_pins(project)

    has_lock = project.has("poetry.lock", "uv.lock", "pdm.lock", "Pipfile.lock",
                           "requirements.lock", "requirements-lock.txt")
    constraints = any(project.glob(pat) for pat in ("constraints*.txt", "requirements*.lock"))
    if sources and not has_lock and not constraints:
        yield Finding(
            "deps.no-lockfile", "low", "No lockfile",
            "Nothing records the exact resolved dependency graph, so two installs "
            "a week apart can differ.",
            fix="Generate one: `uv lock`, `poetry lock`, or `pip-compile requirements.in`.",
        )
    if project.has("pyproject.toml") and project.has("setup.py") and project.has("requirements.txt"):
        yield Finding(
            "deps.multiple-manifests", "low", "Three overlapping Python manifests",
            "pyproject.toml, setup.py and requirements.txt all declare dependencies; "
            "they drift apart silently.",
            fix="Keep pyproject.toml as the single source of truth.",
        )


def _check_javascript(project: Project) -> Iterable[Finding]:
    pkg = project.json("package.json")
    if pkg is None:
        return
    if not project.has("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"):
        yield Finding(
            "deps.js-no-lockfile", "medium", "package.json without a lockfile",
            "npm/yarn will resolve different versions on different machines.",
            path="package.json", fix="Run `npm install` and commit package-lock.json.",
        )
    deps: dict = {}
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = pkg.get(key)
        if isinstance(block, dict):
            deps.update(block)
    for name, spec in sorted(deps.items()):
        if isinstance(spec, str) and spec.strip() in ("*", "latest", ""):
            yield Finding(
                "deps.js-wildcard", "high", f"Wildcard version for {name}",
                f"`{name}: {spec}` installs whatever is newest at build time.",
                path="package.json", fix=f'Pin a range, e.g. `"{name}": "^1.2.3"`.',
            )
    if not pkg.get("license"):
        yield Finding(
            "deps.js-no-license-field", "low", "package.json has no license field",
            "npm warns on publish and consumers cannot tell the terms.",
            path="package.json", fix='Add `"license": "MIT"` (or your chosen SPDX id).',
        )


@register("deps", "Dependencies", "Undeclared imports, unpinned versions, missing lockfiles")
def check_dependencies(project: Project, ctx: dict) -> Iterable[Finding]:
    yield from _check_python(project)
    yield from _check_javascript(project)


def _next_major(spec: str) -> str:
    m = re.search(r"(\d+)", spec)
    return f"{int(m.group(1)) + 1}.0" if m else "2.0"
