"""Runs every enabled check against a project and assembles the report."""
from __future__ import annotations

import time
from collections.abc import Iterable

from .checks import Check, all_checks
from .model import Project, Report


def run(project: Project, only: Iterable[str] = (), skip: Iterable[str] = (),
        offline: bool = False) -> Report:
    only = {c.strip() for c in only if c.strip()}
    skip = {c.strip() for c in skip if c.strip()}
    checks: list[Check] = [
        c for c in all_checks()
        if (not only or c.id in only) and c.id not in skip
        and not (offline and c.network)
    ]

    report = Report(project=project.root.name, root=str(project.root))
    ctx: dict = {"offline": offline}
    started = time.time()

    for check in checks:
        try:
            for finding in check.fn(project, ctx):
                report.add(finding)
        except Exception as exc:  # a broken check must not kill the scan
            report.errors.append(f"check '{check.id}' failed: {type(exc).__name__}: {exc}")

    report.duration = time.time() - started
    report.errors.extend(ctx.get("notes", []))
    report.stats = {
        "files": len(project.files()),
        "python files": len(project.python_files()),
        "python lines": ctx.get("python_lines", 0),
        "test files": ctx.get("test_file_count", 0),
        "tests": ctx.get("test_count", 0),
        "workflows": ctx.get("workflow_count", 0),
        "checks run": len(checks),
    }
    return report
