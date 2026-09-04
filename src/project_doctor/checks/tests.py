"""Test-suite checks: existence, coverage of modules, assert-less tests."""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from ..model import Finding, Project
from . import register

TEST_FILE = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(test|spec)\.[jt]sx?)$")


def test_files(project: Project) -> list[Path]:
    return [p for p in project.files() if TEST_FILE.search(project.rel(p))]


def source_files(project: Project) -> list[Path]:
    out = []
    for p in project.python_files():
        rel = project.rel(p)
        if TEST_FILE.search(rel) or "/tests/" in f"/{rel}" or p.name in ("setup.py", "conftest.py"):
            continue
        out.append(p)
    return out


@register("tests", "Tests", "Missing suite, thin coverage, assert-less and skipped tests")
def check_tests(project: Project, ctx: dict) -> Iterable[Finding]:
    findings: list[Finding] = []
    tests = test_files(project)
    sources = source_files(project)
    ctx["test_file_count"] = len(tests)

    if not tests:
        sev = "high" if len(sources) > 3 else "medium"
        findings.append(Finding(
            "tests.none", sev,
            "No test files found",
            "Nothing matching test_*.py, *_test.py or *.test.js exists, so no change "
            "in this repo is verified by anything.",
            fix="Create tests/test_smoke.py that imports the package and asserts one "
                "real behaviour, then wire `pytest` into CI.",
        ))
        return findings

    if sources and len(tests) * 4 < len(sources):
        findings.append(Finding(
            "tests.thin", "medium",
            f"Thin test suite: {len(tests)} test files for {len(sources)} source files",
            "Under a 1:4 ratio most modules have no direct test.",
            fix="Add tests for the modules with the most branching logic first.",
        ))

    total_tests = 0
    for path in tests:
        if path.suffix != ".py":
            continue
        src = project.read(path)
        if src is None:
            continue
        rel = project.rel(path)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            findings.append(Finding(
                "tests.syntax", "high", f"Test file does not parse: {rel}",
                "A SyntaxError here means the whole file is silently collected as an error.",
                path=rel, fix="Run `python -m py_compile` on it and fix the error.",
            ))
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                total_tests += 1
                has_assert = any(
                    isinstance(n, (ast.Assert, ast.Raise)) or
                    (isinstance(n, ast.Call) and _is_assert_call(n))
                    for n in ast.walk(node)
                )
                if not has_assert:
                    findings.append(Finding(
                        "tests.no-assert", "medium",
                        f"Test asserts nothing: {node.name}",
                        "The function runs code but never checks a result, so it passes "
                        "even when the behaviour is wrong.",
                        path=rel, line=node.lineno,
                        fix="Add an assertion, or delete the test if it is dead weight.",
                    ))
        for i, line in enumerate(src.splitlines(), 1):
            if re.search(r"@(pytest\.mark\.)?(skip|xfail)\b", line) and "skipif" not in line:
                findings.append(Finding(
                    "tests.skipped", "low",
                    "Unconditionally skipped test",
                    "A permanently skipped test gives false confidence in the pass count.",
                    path=rel, line=i,
                    fix="Fix and re-enable it, or delete it.",
                ))
    ctx["test_count"] = total_tests

    if not project.has("pytest.ini", "tox.ini", "conftest.py", "tests/conftest.py") and \
       not _config_mentions(project, "pytest"):
        findings.append(Finding(
            "tests.no-runner-config", "low",
            "No pytest configuration",
            "Without [tool.pytest.ini_options] the test paths, import mode and "
            "warning filters differ between machines.",
            fix="Add `[tool.pytest.ini_options]` with `testpaths = [\"tests\"]` to pyproject.toml.",
        ))

    if not _config_mentions(project, "coverage") and not project.has(".coveragerc"):
        findings.append(Finding(
            "tests.no-coverage", "low",
            "No coverage configuration",
            "Nothing measures which lines the suite actually executes.",
            fix="Add pytest-cov and run `pytest --cov=src --cov-report=term-missing`.",
        ))
    return findings


def _is_assert_call(node: ast.Call) -> bool:
    f = node.func
    name = getattr(f, "attr", None) or getattr(f, "id", None) or ""
    return name.startswith("assert") or name in ("raises", "warns", "fail")


def _config_mentions(project: Project, needle: str) -> bool:
    for name in ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini"):
        text = project.read_name(name)
        if text and needle in text:
            return True
    return False
