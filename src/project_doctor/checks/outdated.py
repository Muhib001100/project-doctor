"""Outdated package check. Queries the PyPI and npm registries (network)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from ..model import Finding, Project
from . import register
from .dependencies import parse_pyproject_deps, parse_requirements

USER_AGENT = "project-doctor (+https://github.com/)"
TIMEOUT = 8
MAX_LOOKUPS = 80


def _get_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def pypi_latest(name: str) -> str | None:
    data = _get_json(f"https://pypi.org/pypi/{name}/json")
    if not data:
        return None
    return (data.get("info") or {}).get("version")


def npm_latest(name: str) -> str | None:
    data = _get_json(f"https://registry.npmjs.org/{name}/latest")
    if not data:
        return None
    return data.get("version")


def parse_version(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts[:4]) or (0,)


def pinned_versions(project: Project) -> dict[str, str]:
    """name -> exact pinned version, for == pins only."""
    pins: dict[str, str] = {}
    for p in project.files():
        rel = project.rel(p)
        if not re.fullmatch(r"(requirements[\w.-]*\.txt|requirements/[\w.-]+\.txt)", rel):
            continue
        for _, name, rest in parse_requirements(project.read(p) or ""):
            m = re.match(r"==\s*([0-9][\w.*+!-]*)", rest)
            if m and "*" not in m.group(1):
                pins[name] = m.group(1)
    text = project.read_name("pyproject.toml")
    if text:
        _, specs = parse_pyproject_deps(text)
        for spec, name in specs:
            m = re.search(r"==\s*([0-9][\w.*+!-]*)", spec)
            if m and "*" not in m.group(1):
                pins[name] = m.group(1)
    return pins


@register("outdated", "Outdated packages",
          "Compares pinned versions against the PyPI/npm registries", network=True)
def check_outdated(project: Project, ctx: dict) -> Iterable[Finding]:
    if ctx.get("offline"):
        return []
    findings: list[Finding] = []

    py_pins = pinned_versions(project)
    js_pins: dict[str, str] = {}
    pkg = project.json("package.json")
    if pkg:
        for key in ("dependencies", "devDependencies"):
            for name, spec in (pkg.get(key) or {}).items():
                if isinstance(spec, str):
                    m = re.match(r"^[\^~]?\s*(\d+\.\d+\.\d+)", spec.strip())
                    if m:
                        js_pins[name] = m.group(1)

    jobs: list[tuple[str, str, str]] = []
    jobs += [("pypi", n, v) for n, v in list(py_pins.items())[:MAX_LOOKUPS]]
    jobs += [("npm", n, v) for n, v in list(js_pins.items())[: max(0, MAX_LOOKUPS - len(jobs))]]
    if not jobs:
        return []

    def lookup(job):
        eco, name, current = job
        latest = pypi_latest(name) if eco == "pypi" else npm_latest(name)
        return eco, name, current, latest

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lookup, jobs))

    reachable = any(latest for _, _, _, latest in results)
    if not reachable:
        ctx.setdefault("notes", []).append(
            "Registry lookups failed (no network?) — outdated check skipped."
        )
        return []

    for eco, name, current, latest in results:
        if not latest:
            continue
        cur_v, new_v = parse_version(current), parse_version(latest)
        if new_v <= cur_v:
            continue
        major_gap = new_v[0] - cur_v[0]
        minor_gap = (new_v[0], new_v[1] if len(new_v) > 1 else 0) > (cur_v[0], cur_v[1] if len(cur_v) > 1 else 0)
        if major_gap >= 2:
            sev = "high"
        elif major_gap == 1:
            sev = "medium"
        elif minor_gap:
            sev = "low"
        else:
            sev = "info"
        where = "pyproject.toml / requirements.txt" if eco == "pypi" else "package.json"
        findings.append(Finding(
            "outdated.package", sev,
            f"{name} {current} → {latest}",
            f"Pinned at {current}; the {eco} registry has {latest}." +
            (" Major version jump — expect breaking changes." if major_gap else ""),
            path=where,
            fix=f"Bump to {latest} after reading its changelog, then re-run the test suite.",
        ))
    return findings
