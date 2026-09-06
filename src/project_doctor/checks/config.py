"""Repo hygiene: .gitignore, licence, committed secrets and junk, packaging config."""
from __future__ import annotations

import re
from collections.abc import Iterable

from ..model import Finding, Project
from . import register
from .dependencies import in_auxiliary_tree

SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key id", "critical"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token", "critical"),
    (r"github_pat_[A-Za-z0-9_]{60,}", "GitHub fine-grained token", "critical"),
    (r"gh[pousr]_[A-Za-z0-9]{36,}", "GitHub token", "critical"),
    (r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}", "OpenAI-style API key", "critical"),
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic API key", "critical"),
    (r"xox[abposr]-[A-Za-z0-9-]{10,}", "Slack token", "critical"),
    (r"AIza[0-9A-Za-z_-]{35}", "Google API key", "critical"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "private key", "critical"),
    (r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd)\s*[:=]\s*[\"'][^\"'\s{}$]{12,}[\"']",
     "hardcoded credential", "high"),
    (r"(?i)postgres(?:ql)?://[^\s:@\"']+:[^\s@\"']+@", "database URL with password", "critical"),
    (r"(?i)mongodb(?:\+srv)?://[^\s:@\"']+:[^\s@\"']+@", "MongoDB URL with password", "critical"),
]

# Put `# project-doctor: ignore` (or the detect-secrets pragma) on a line to
# silence a secret match you have reviewed.
IGNORE_PRAGMA = re.compile(r"(?i)(project-doctor:\s*ignore|pragma:\s*allowlist secret|noqa:\s*secret)")

PLACEHOLDER = re.compile(
    r"(?i)(example|changeme|your[_-]?(key|token|secret)|placeholder|xxx+|<[^>]+>|\$\{|dummy|test123|sample|redacted|fake)"
)

JUNK = [
    ("__pycache__/", "medium", "Python bytecode cache"),
    ("*.pyc", "medium", "compiled Python files"),
    (".DS_Store", "low", "macOS folder metadata"),
    ("Thumbs.db", "low", "Windows thumbnail cache"),
    ("*.log", "low", "log files"),
    ("*.sqlite3", "medium", "a database file"),
    ("node_modules/*", "high", "the entire node_modules tree"),
    (".venv/*", "high", "a virtualenv"),
    ("venv/*", "high", "a virtualenv"),
    ("*.swp", "low", "editor swap files"),
]

GITIGNORE_ESSENTIALS = {
    "python": ["__pycache__/", "*.py[cod]", ".venv", "*.egg-info", ".pytest_cache", ".env"],
    "node": ["node_modules/", "dist/", ".env"],
}


def _scan_secrets(project: Project) -> Iterable[Finding]:
    """Regex sweep for credentials that should never be in version control."""
    skip_suffix = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip",
                   ".woff", ".woff2", ".ico", ".svg"}
    scanned = 0
    for path in project.files():
        rel = project.rel(path)
        if path.suffix.lower() in skip_suffix or rel.endswith(("lock", ".lock")):
            continue
        text = project.read(path)
        if text is None:
            continue
        scanned += 1
        if scanned > 4000:
            return
        lines = text.splitlines()
        for pattern, label, sev in SECRET_PATTERNS:
            m = re.search(pattern, text)
            if not m or PLACEHOLDER.search(m.group(0)):
                continue
            line = text.count("\n", 0, m.start()) + 1
            if line <= len(lines) and IGNORE_PRAGMA.search(lines[line - 1]):
                continue
            is_example = in_auxiliary_tree(rel) or re.search(
                r"(?i)(\.example$|\.sample$|\.template$|\.md$|\.rst$|\.txt$"
                r"|(^|/)(fixtures?|tests?|docs?|examples?|samples?)/)", rel
            )
            # Prose documentation shows fake credentials constantly; only
            # high-entropy provider-specific tokens are worth reporting there.
            if is_example and label == "hardcoded credential":
                continue
            yield Finding(
                "config.secret", "medium" if is_example else sev,
                f"Possible {label} committed to the repo",
                f"Matched in `{rel}`. Anything pushed to GitHub must be treated as "
                "public and rotated, even after a force-push.",
                path=rel, line=line,
                fix="Rotate the credential now, move it to an environment variable, "
                    "and purge history with `git filter-repo`. Add "
                    "`# project-doctor: ignore` if this is a known-safe sample.",
            )
            break


def _scan_env_files(project: Project) -> Iterable[Finding]:
    for p in project.files():
        rel = project.rel(p)
        if re.fullmatch(r"(.*/)?\.env(\.(local|production|prod|dev|development))?", rel):
            fixture = re.search(r"(?i)(^|/)(tests?|fixtures?|examples?)/", rel)
            yield Finding(
                "config.env-committed", "medium" if fixture else "high",
                f"`{rel}` is in the repository",
                "Env files hold real credentials and are the single most common "
                "accidental leak on GitHub.",
                path=rel,
                fix="Delete it, add `.env` to .gitignore, and commit a `.env.example` "
                    "with empty values instead.",
            )


def _check_gitignore(project: Project, gitignore: str) -> Iterable[Finding]:
    if not gitignore:
        yield Finding(
            "config.no-gitignore", "high", "No .gitignore",
            "Build output, virtualenvs, caches and secrets will be committed by default.",
            fix="Add a .gitignore (github.com/github/gitignore has vetted templates).",
        )
        return
    wanted: list[str] = []
    if project.python_files():
        wanted += GITIGNORE_ESSENTIALS["python"]
    if project.has("package.json"):
        wanted += GITIGNORE_ESSENTIALS["node"]
    missing = [e for e in wanted if e.rstrip("/") not in gitignore]
    if missing:
        yield Finding(
            "config.gitignore-gaps", "low",
            f"`.gitignore` is missing {len(missing)} common entries",
            "Not ignored: " + ", ".join(missing[:8]),
            path=".gitignore", fix="Append the missing patterns.",
        )


def _check_junk(project: Project, gitignore: str) -> Iterable[Finding]:
    import fnmatch
    import os

    for entry in sorted(os.listdir(project.root)):
        if entry in ("node_modules", ".venv", "venv") and (project.root / entry).is_dir():
            if entry not in gitignore:
                yield Finding(
                    "config.junk", "high",
                    f"`{entry}/` exists and is not in .gitignore",
                    "If it is tracked, clones are huge and diffs are unreadable.",
                    path=entry + "/",
                    fix=f"Add `{entry}/` to .gitignore and `git rm -r --cached {entry}`.",
                )
    all_rel = [project.rel(p) for p in project.files()]
    for pattern, sev, label in JUNK:
        hits = [r for r in all_rel
                if fnmatch.fnmatch(r, pattern) or fnmatch.fnmatch(r, "*/" + pattern)]
        if hits and pattern.rstrip("/*") not in gitignore:
            yield Finding(
                "config.junk", sev,
                f"{label.capitalize()} committed ({len(hits)} file(s))",
                "Example: " + hits[0], path=hits[0],
                fix=f"Add `{pattern}` to .gitignore and `git rm --cached` the files.",
            )


def _check_license_and_size(project: Project) -> Iterable[Finding]:
    if not project.find_name("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"):
        yield Finding(
            "config.no-license", "high", "No LICENSE file",
            "Without one the code is 'all rights reserved' by default - nobody can "
            "legally use, fork or contribute to it, which defeats publishing it.",
            fix="Add a LICENSE file. MIT is the usual default for tools like this.",
        )
    for p in project.files():
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > 10_000_000:
            yield Finding(
                "config.large-file", "medium",
                f"Large file: {project.rel(p)} ({size // 1_000_000} MB)",
                "GitHub warns above 50 MB and rejects above 100 MB; large blobs stay "
                "in history forever.",
                path=project.rel(p), fix="Move it to Git LFS or a release asset.",
            )


def _check_packaging(project: Project) -> Iterable[Finding]:
    if not project.python_files():
        return
    pyproject = project.read_name("pyproject.toml")
    if pyproject:
        rules = [
            ("[build-system]", "config.no-build-system", "medium",
             "pyproject.toml has no [build-system]",
             "pip falls back to legacy setuptools behaviour and the build is not reproducible.",
             'Add [build-system] with requires = ["hatchling"] and build-backend = "hatchling.build".'),
            ("requires-python", "config.no-requires-python", "medium",
             "No `requires-python` declared",
             "pip will install the package on Python versions it cannot run on.",
             'Add `requires-python = ">=3.9"` to [project].'),
            ("version", "config.no-version", "low",
             "No version declared in pyproject.toml",
             "Consumers cannot pin a release.", 'Add `version = "0.1.0"` to [project].'),
        ]
        for needle, cid, sev, title, detail, fix in rules:
            if needle not in pyproject:
                yield Finding(cid, sev, title, detail, path="pyproject.toml", fix=fix)
    if not project.has(".pre-commit-config.yaml") and len(project.python_files()) > 5:
        yield Finding(
            "config.no-precommit", "info", "No pre-commit hooks",
            "Formatting and lint errors reach CI instead of being caught locally.",
            fix="Add .pre-commit-config.yaml with ruff and run `pre-commit install`.",
        )


@register("config", "Configuration & hygiene",
          "Secrets, .gitignore gaps, committed junk, licence and packaging problems")
def check_config(project: Project, ctx: dict) -> Iterable[Finding]:
    gitignore = project.read_name(".gitignore") or ""
    yield from _scan_secrets(project)
    yield from _scan_env_files(project)
    yield from _check_gitignore(project, gitignore)
    yield from _check_junk(project, gitignore)
    yield from _check_license_and_size(project)
    yield from _check_packaging(project)
