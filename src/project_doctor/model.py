"""Core data types shared by every check."""
from __future__ import annotations

import fnmatch
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SEVERITIES = ("critical", "high", "medium", "low", "info")

# Points deducted from the 100-point health score, per finding.
WEIGHTS = {"critical": 20.0, "high": 7.0, "medium": 2.5, "low": 0.8, "info": 0.0}

# Diminishing returns. Repeats of the same check decay, and both a single check
# and a whole category are capped, so one noisy check (200 long functions) or
# one weak area cannot zero out an otherwise healthy project.
REPEAT_DECAY = 0.55
MAX_DEDUCTION_PER_CHECK = 8.0
MAX_DEDUCTION_PER_CATEGORY = 15.0

# Two kinds of finding score differently.
#
#   Absolute  - presence or absence of something the project should have, or a
#               fact that is equally bad at any size: no LICENSE, no CI, a
#               leaked key, a file that does not parse. Counted as-is.
#   Density   - things that naturally accumulate with codebase size: long
#               functions, complex functions, TODO-grade nits. Counted per
#               thousand lines, so a 300k-line project is not punished for
#               being large.
DENSITY_PREFIXES = ("quality.",)
DENSITY_CHECKS = {
    "tests.no-assert", "tests.skipped",
    "deps.undeclared", "deps.unpinned", "deps.no-upper-bound", "deps.js-wildcard",
    "docs.broken-link", "docs.placeholder",
    "ci.unpinned-action", "ci.outdated-action",
    "config.junk", "config.large-file",
    "outdated.package",
}


def is_density_check(check: str) -> bool:
    """True if this check's finding count scales with codebase size."""
    return check in DENSITY_CHECKS or check.startswith(DENSITY_PREFIXES)


@dataclass(frozen=True)
class Finding:
    check: str          # check id, e.g. "deps.undeclared"
    severity: str       # one of SEVERITIES
    title: str          # one line, human readable
    detail: str = ""    # longer explanation
    path: str = ""      # repo-relative path, if applicable
    line: int = 0       # 1-based line number, 0 if not applicable
    fix: str = ""       # concrete remediation

    def location(self) -> str:
        if not self.path:
            return ""
        return f"{self.path}:{self.line}" if self.line else self.path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_IGNORES = [
    ".git", ".hg", ".svn", ".tox", ".nox", ".venv", "venv", "env",
    "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "dist", "build", "site-packages", ".eggs", "*.egg-info",
    ".next", ".nuxt", "target", "vendor", "coverage", "htmlcov", ".idea",
    ".gradle", ".terraform", "bower_components",
]

TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json",
    ".toml", ".cfg", ".ini", ".yaml", ".yml", ".md", ".rst", ".txt", ".sh",
    ".bash", ".env", ".example", ".lock", ".gitignore", ".dockerignore",
    ".html", ".css", ".sql", "", ".rb", ".go", ".rs", ".java", ".php",
}

MAX_READ_BYTES = 2_000_000


class Project:
    """A filesystem view of the project under inspection, with caching."""

    def __init__(self, root: str | os.PathLike[str], extra_ignores: Iterable[str] = ()):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"not a directory: {self.root}")
        self.ignores = list(DEFAULT_IGNORES) + list(extra_ignores)
        self._files: list[Path] | None = None
        self._text_cache: dict[str, str | None] = {}

    # ---------------------------------------------------------------- paths
    def _ignored(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, pat) for pat in self.ignores)

    def files(self) -> list[Path]:
        if self._files is None:
            found: list[Path] = []
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = sorted(d for d in dirnames if not self._ignored(d))
                for fn in sorted(filenames):
                    if self._ignored(fn):
                        continue
                    found.append(Path(dirpath) / fn)
            self._files = found
        return self._files

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def glob(self, pattern: str) -> list[Path]:
        return [p for p in self.files() if fnmatch.fnmatch(self.rel(p), pattern)]

    def by_suffix(self, *suffixes: str) -> list[Path]:
        s = {x.lower() for x in suffixes}
        return [p for p in self.files() if p.suffix.lower() in s]

    def python_files(self) -> list[Path]:
        return self.by_suffix(".py")

    def has(self, *names: str) -> bool:
        return any((self.root / n).exists() for n in names)

    def first_existing(self, *names: str) -> Path | None:
        for n in names:
            p = self.root / n
            if p.exists():
                return p
        return None

    def find_name(self, *names: str) -> Path | None:
        """Find a file anywhere in the tree by exact basename (case-insensitive)."""
        wanted = {n.lower() for n in names}
        for p in self.files():
            if p.name.lower() in wanted:
                return p
        return None

    # ----------------------------------------------------------------- text
    def read(self, path: Path) -> str | None:
        key = str(path)
        if key not in self._text_cache:
            try:
                if path.stat().st_size > MAX_READ_BYTES:
                    self._text_cache[key] = None
                else:
                    self._text_cache[key] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._text_cache[key] = None
        return self._text_cache[key]

    def read_name(self, name: str) -> str | None:
        p = self.root / name
        return self.read(p) if p.is_file() else None

    def json(self, name: str) -> dict[str, Any] | None:
        raw = self.read_name(name)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None


@dataclass
class Report:
    project: str
    root: str
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration: float = 0.0
    # Set when findings are filtered for display, so --min-severity cannot
    # inflate the score.
    score_override: int | None = None

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(SEVERITIES, 0)
        for f in self.findings:
            if f.severity in out:
                out[f.severity] += 1
        return out

    def score(self) -> int:
        """100 minus weighted deductions. See DENSITY_CHECKS for the two modes."""
        if self.score_override is not None:
            return self.score_override

        kloc = max(1.0, float(self.stats.get("python lines") or 0) / 1000.0)

        tally: dict[tuple[str, str], int] = {}
        for f in self.findings:
            key = (f.check, f.severity)
            tally[key] = tally.get(key, 0) + 1

        per_check: dict[str, float] = {}
        for (check, severity), count in tally.items():
            weight = WEIGHTS.get(severity, 0.0)
            if not weight:
                continue
            effective = count / kloc if is_density_check(check) else float(count)
            # Geometric sum of weight * decay^i, extended to fractional counts:
            # one finding costs the full weight, each further one costs less,
            # and the total converges to weight / (1 - decay).
            deduction = weight * (1 - REPEAT_DECAY ** effective) / (1 - REPEAT_DECAY)
            cap = max(MAX_DEDUCTION_PER_CHECK, weight)
            per_check[check] = min(cap, per_check.get(check, 0.0) + deduction)

        # Critical findings bypass the category cap: a leaked key or a syntax
        # error must always move the number.
        critical_checks = {f.check for f in self.findings if f.severity == "critical"}
        critical_total = sum(per_check.pop(c, 0.0) for c in critical_checks)

        per_category: dict[str, float] = {}
        for check, points in per_check.items():
            category = check.split(".")[0]
            per_category[category] = min(
                MAX_DEDUCTION_PER_CATEGORY, per_category.get(category, 0.0) + points
            )
        return max(0, min(100, round(100 - critical_total - sum(per_category.values()))))

    def grade(self) -> str:
        s = self.score()
        for cut, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F")):
            if s >= cut:
                return letter
        return "F"

    def sorted_findings(self) -> list[Finding]:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        return sorted(self.findings, key=lambda f: (order.get(f.severity, 9), f.check, f.path, f.line))

    def by_severity(self) -> Iterator[tuple[str, list[Finding]]]:
        groups: dict[str, list[Finding]] = {s: [] for s in SEVERITIES}
        for f in self.sorted_findings():
            groups.setdefault(f.severity, []).append(f)
        for s in SEVERITIES:
            if groups[s]:
                yield s, groups[s]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "root": self.root,
            "score": self.score(),
            "grade": self.grade(),
            "counts": self.counts(),
            "stats": self.stats,
            "duration_seconds": round(self.duration, 3),
            "errors": self.errors,
            "findings": [f.to_dict() for f in self.sorted_findings()],
        }
