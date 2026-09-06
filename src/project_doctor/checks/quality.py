"""Static code-quality checks, AST based, no third-party linters required."""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable

from ..model import Finding, Project
from . import register

MAX_FUNC_LINES = 60
MAX_COMPLEXITY = 12
MAX_ARGS = 6
MAX_FILE_LINES = 800
MAX_NESTING = 5

MATCH_NODE = getattr(ast, "Match", ())  # Python 3.10+

BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                ast.With, ast.AsyncWith, ast.Assert, ast.IfExp, ast.comprehension)


def complexity(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, BRANCH_NODES):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif MATCH_NODE and isinstance(child, MATCH_NODE):
            score += len(child.cases)
    return score


def nesting_depth(node: ast.AST, depth: int = 0) -> int:
    best = depth
    for child in ast.iter_child_nodes(node):
        step = 1 if isinstance(child, (ast.If, ast.For, ast.While, ast.With,
                                       ast.Try, ast.AsyncFor, ast.AsyncWith)) else 0
        best = max(best, nesting_depth(child, depth + step))
    return best


@register("quality", "Code quality",
          "Complexity, long functions, bare excepts, mutable defaults, dangerous calls")
def check_quality(project: Project, ctx: dict) -> Iterable[Finding]:
    findings: list[Finding] = []
    total_lines = 0
    todo_count = 0
    todo_first = None

    for path in project.python_files():
        rel = project.rel(path)
        src = project.read(path)
        if src is None:
            continue
        lines = src.splitlines()
        total_lines += len(lines)
        is_test = "test" in rel

        for i, line in enumerate(lines, 1):
            if re.search(r"#\s*(TODO|FIXME|XXX|HACK)\b", line):
                todo_count += 1
                if todo_first is None:
                    todo_first = (rel, i, line.strip()[:80])

        if len(lines) > MAX_FILE_LINES:
            findings.append(Finding(
                "quality.long-file", "low", f"{rel} is {len(lines)} lines",
                f"Files over {MAX_FILE_LINES} lines are hard to navigate and review.",
                path=rel, fix="Split it along its natural seams into separate modules.",
            ))

        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            findings.append(Finding(
                # Test suites sometimes ship a deliberately broken file as a
                # fixture, so a parse failure there is not project-critical.
                "quality.syntax-error", "high" if is_test else "critical",
                f"SyntaxError in {rel}",
                f"Line {exc.lineno}: {exc.msg}. This file cannot be imported at all.",
                path=rel, line=exc.lineno or 0, fix="Fix the syntax error.",
            ))
            continue

        for node in ast.walk(tree):
            # bare except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                findings.append(Finding(
                    "quality.bare-except", "medium", "Bare `except:` swallows everything",
                    "It catches KeyboardInterrupt and SystemExit too, so the process "
                    "cannot be stopped cleanly and real bugs are hidden.",
                    path=rel, line=node.lineno,
                    fix="Catch the specific exception, or `except Exception:` at minimum.",
                ))
            # except: pass
            if isinstance(node, ast.ExceptHandler) and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                findings.append(Finding(
                    "quality.silent-except", "medium", "Exception caught and ignored",
                    "The `except ...: pass` block discards the error with no log, so "
                    "failures are invisible in production.",
                    path=rel, line=node.lineno,
                    fix="Log it, re-raise it, or add a comment saying why it is safe to ignore.",
                ))
            # wildcard import
            if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
                findings.append(Finding(
                    "quality.wildcard-import", "low",
                    f"Wildcard import from {node.module or '?'}",
                    "Shadows names unpredictably and defeats static analysis.",
                    path=rel, line=node.lineno, fix="Import the names you actually use.",
                ))
            # eval / exec
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                findings.append(Finding(
                    "quality.eval", "medium" if is_test else "high",
                    f"Use of `{node.func.id}()`",
                    "Executes arbitrary code; if any part of the input is user-controlled "
                    "this is remote code execution.",
                    path=rel, line=node.lineno,
                    fix="Use ast.literal_eval, a dict dispatch, or json.loads instead.",
                ))
            # subprocess shell=True
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        findings.append(Finding(
                            "quality.shell-true", "medium" if is_test else "high",
                            "subprocess called with shell=True",
                            "Any interpolated value becomes shell syntax — classic command injection.",
                            path=rel, line=node.lineno,
                            fix="Pass a list of arguments and drop shell=True.",
                        ))
            # assert in non-test code
            if isinstance(node, ast.Assert) and not is_test:
                pass  # too noisy to flag individually; covered by info below

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # mutable default arguments
                for default in list(node.args.defaults) + [d for d in node.args.kw_defaults if d]:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                        isinstance(default, ast.Call) and isinstance(default.func, ast.Name)
                        and default.func.id in ("list", "dict", "set")
                    ):
                        findings.append(Finding(
                            "quality.mutable-default", "medium",
                            f"Mutable default argument in `{node.name}()`",
                            "The default object is created once and shared across every call, "
                            "so state leaks between invocations.",
                            path=rel, line=node.lineno,
                            fix="Use `None` as the default and build the object inside the function.",
                        ))
                        break
                length = (node.end_lineno or node.lineno) - node.lineno
                if length > MAX_FUNC_LINES and not is_test:
                    findings.append(Finding(
                        "quality.long-function", "low",
                        f"`{node.name}()` is {length} lines",
                        f"Over {MAX_FUNC_LINES} lines; hard to test in isolation.",
                        path=rel, line=node.lineno, fix="Extract the distinct steps into helpers.",
                    ))
                cx = complexity(node)
                if cx > MAX_COMPLEXITY and not is_test:
                    findings.append(Finding(
                        "quality.complexity", "medium",
                        f"`{node.name}()` has cyclomatic complexity {cx}",
                        f"Above {MAX_COMPLEXITY} the number of paths makes full test "
                        "coverage impractical.",
                        path=rel, line=node.lineno,
                        fix="Split the branches into named helper functions or a dispatch table.",
                    ))
                nargs = len(node.args.args) + len(node.args.kwonlyargs) + len(node.args.posonlyargs)
                if nargs > MAX_ARGS:
                    findings.append(Finding(
                        "quality.too-many-args", "low",
                        f"`{node.name}()` takes {nargs} parameters",
                        "Long signatures are easy to call wrongly by position.",
                        path=rel, line=node.lineno,
                        fix="Group related parameters into a dataclass or keyword-only options object.",
                    ))
                if nesting_depth(node) > MAX_NESTING:
                    findings.append(Finding(
                        "quality.deep-nesting", "low",
                        f"`{node.name}()` nests {nesting_depth(node)} levels deep",
                        "Deep nesting hides the happy path.",
                        path=rel, line=node.lineno,
                        fix="Use early returns / guard clauses to flatten it.",
                    ))

    if todo_count > 15 and todo_first:
        findings.append(Finding(
            "quality.todos", "info", f"{todo_count} TODO/FIXME comments",
            f"First one: {todo_first[2]}",
            path=todo_first[0], line=todo_first[1],
            fix="Convert the real ones into GitHub issues and delete the stale ones.",
        ))
    ctx["python_lines"] = total_lines
    ctx["todo_count"] = todo_count
    return findings
