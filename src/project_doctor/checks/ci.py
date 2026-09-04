"""GitHub Actions / CI checks. Regex based, so no PyYAML dependency."""
from __future__ import annotations

import re
from collections.abc import Iterable

from ..model import Finding, Project
from . import register

USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
DEPRECATED = {
    "actions/checkout": 4, "actions/setup-python": 5, "actions/setup-node": 4,
    "actions/cache": 4, "actions/upload-artifact": 4, "actions/download-artifact": 4,
}
TEST_COMMAND = re.compile(
    r"(?i)\b(pytest|py\.test|python -m (unittest|pytest)|nox|tox|hatch run|"
    r"coverage run|npm (run )?test|yarn test|pnpm test|go test|cargo test|"
    r"make (test|ci|check)|bazel test|\./run-tests)\b"
)
LINT_COMMAND = re.compile(r"(?i)\b(ruff|flake8|pylint|mypy|eslint|black --check|golangci-lint|clippy)\b")


def workflows(project: Project):
    out = []
    for p in project.files():
        rel = project.rel(p)
        if rel.startswith(".github/workflows/") and p.suffix in (".yml", ".yaml"):
            out.append((rel, project.read(p) or ""))
    return out


@register("ci", "CI / GitHub Actions",
          "Missing workflows, unpinned actions, no test step, unsafe triggers")
def check_ci(project: Project, ctx: dict) -> Iterable[Finding]:
    findings: list[Finding] = []
    wfs = workflows(project)
    other_ci = project.has(".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml",
                           ".circleci/config.yml", "Jenkinsfile")
    ctx["workflow_count"] = len(wfs)

    if not wfs:
        if other_ci:
            findings.append(Finding(
                "ci.non-github", "info", "CI is configured outside GitHub Actions",
                "Found a non-Actions CI config; GitHub will not show status checks on PRs.",
                fix="Optional: mirror the pipeline in .github/workflows/ci.yml.",
            ))
        else:
            findings.append(Finding(
                "ci.none", "high", "No CI workflow",
                "Nothing runs tests or lint on push or pull request, so a broken commit "
                "reaches main unnoticed.",
                fix="Add .github/workflows/ci.yml running your test suite on push and "
                    "pull_request across the Python versions you support.",
            ))
        return findings

    any_tests = False
    any_lint = False
    any_matrix = False
    any_cache = False
    has_permissions = False

    for rel, text in wfs:
        lines = text.splitlines()
        if TEST_COMMAND.search(text):
            any_tests = True
        if LINT_COMMAND.search(text):
            any_lint = True
        if re.search(r"^\s*(strategy|matrix)\s*:", text, re.M):
            any_matrix = True
        if "actions/cache" in text or re.search(r"^\s*cache\s*:", text, re.M):
            any_cache = True
        if re.search(r"^\s*permissions\s*:", text, re.M):
            has_permissions = True

        if not re.search(r"^\s*on\s*:|^\s*[\"']on[\"']\s*:", text, re.M):
            findings.append(Finding(
                "ci.no-trigger", "high", f"{rel} has no `on:` trigger",
                "The workflow will never run.",
                path=rel, fix="Add `on: [push, pull_request]`.",
            ))
        elif not re.search(r"pull_request", text) and not re.search(
            r"^\s*(release|schedule|workflow_dispatch|workflow_call)\s*:", text, re.M
        ):
            findings.append(Finding(
                "ci.no-pr-trigger", "medium", f"{rel} does not run on pull requests",
                "Contributions are only checked after they are merged.",
                path=rel, fix="Add `pull_request` to the `on:` triggers.",
            ))

        if re.search(r"pull_request_target", text) and re.search(r"actions/checkout", text):
            findings.append(Finding(
                "ci.pr-target", "critical",
                f"{rel} uses pull_request_target with a checkout",
                "This runs untrusted fork code with write-scoped secrets available — "
                "a well-known repository takeover pattern.",
                path=rel,
                fix="Switch to `pull_request`, or never check out the PR head under "
                    "pull_request_target.",
            ))

        for i, line in enumerate(lines, 1):
            m = USES.match(line)
            if not m:
                continue
            ref = m.group(1).strip().strip("'\"")
            if "@" not in ref:
                findings.append(Finding(
                    "ci.unpinned-action", "medium", f"Action not pinned: {ref}",
                    "Without a version or SHA the default branch is used, so upstream "
                    "changes run in your CI without review.",
                    path=rel, line=i, fix=f"Pin it: `uses: {ref}@v1` or a full commit SHA.",
                ))
                continue
            name, _, version = ref.partition("@")
            if version in ("main", "master"):
                findings.append(Finding(
                    "ci.floating-action", "high", f"Action tracks a branch: {ref}",
                    "Any push to that branch upstream executes in your workflow, with "
                    "access to your secrets.",
                    path=rel, line=i, fix=f"Pin to a release tag or SHA: `{name}@v4`.",
                ))
            vm = re.match(r"^v(\d+)", version)
            if vm and name in DEPRECATED and int(vm.group(1)) < DEPRECATED[name]:
                findings.append(Finding(
                    "ci.outdated-action", "medium",
                    f"{name}@{version} is outdated (current major: v{DEPRECATED[name]})",
                    "Old action majors run on deprecated Node runtimes and get "
                    "warning-annotated, then eventually disabled by GitHub.",
                    path=rel, line=i, fix=f"Bump to `{name}@v{DEPRECATED[name]}`.",
                ))
            if re.search(r"\$\{\{\s*github\.event\.(issue|pull_request|comment)[^}]*\}\}", text):
                pass

        for i, line in enumerate(lines, 1):
            if re.search(r"\$\{\{\s*github\.event\.(issue\.title|issue\.body|pull_request\.title|pull_request\.body|comment\.body|head_ref)", line) and "run:" in text:
                findings.append(Finding(
                    "ci.script-injection", "high",
                    "Untrusted GitHub event data interpolated into a workflow",
                    "Attacker-controlled text (PR title, branch name, comment body) is "
                    "expanded directly into shell — script injection.",
                    path=rel, line=i,
                    fix="Pass it through an `env:` variable and reference \"$VAR\" in the script.",
                ))
                break

    if not any_tests:
        findings.append(Finding(
            "ci.no-test-step", "high", "No workflow runs the test suite",
            "The workflows exist but none of them invokes pytest/npm test, so CI is "
            "green regardless of whether the code works.",
            fix="Add a `run: pytest` step (or your runner) to the main workflow.",
        ))
    if not any_lint:
        findings.append(Finding(
            "ci.no-lint-step", "low", "No lint or type-check step in CI",
            "Style and type regressions are only caught in review.",
            fix="Add `run: ruff check .` and, if you use type hints, `mypy src`.",
        ))
    if not any_matrix:
        findings.append(Finding(
            "ci.no-matrix", "low", "CI runs on a single environment",
            "No version matrix, so breakage on other supported Python/Node versions "
            "or on Windows/macOS is invisible.",
            fix="Add `strategy.matrix` over the versions listed in requires-python.",
        ))
    if not any_cache:
        findings.append(Finding(
            "ci.no-cache", "info", "No dependency caching in CI",
            "Every run re-downloads dependencies, which is slow and rate-limit prone.",
            fix="Set `cache: pip` on actions/setup-python, or use actions/cache.",
        ))
    if not has_permissions:
        findings.append(Finding(
            "ci.no-permissions", "medium", "No explicit `permissions:` block",
            "Workflows inherit the repository default GITHUB_TOKEN scope, which is "
            "often broader than the job needs.",
            fix="Add `permissions: contents: read` at the top of each workflow.",
        ))
    if not project.has(".github/dependabot.yml", ".github/dependabot.yaml"):
        findings.append(Finding(
            "ci.no-dependabot", "info", "Dependabot is not configured",
            "Nothing opens PRs for security updates to your dependencies or actions.",
            fix="Add .github/dependabot.yml with the `pip` and `github-actions` ecosystems.",
        ))
    return findings
