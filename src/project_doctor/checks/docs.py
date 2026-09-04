"""README and documentation checks."""
from __future__ import annotations

import re
from collections.abc import Iterable

from ..model import Finding, Project
from . import register

SECTION_HINTS = {
    "install": r"(?i)^#{1,4}\s*(installation|install|getting started|setup|quick ?start)",
    "usage": r"(?i)^#{1,4}\s*(usage|how to use|examples?|quick ?start|getting started)",
    "license": r"(?i)^#{1,4}\s*(licen[cs]e)",
}

PLACEHOLDER_TEXT = re.compile(
    r"(?i)(TODO: |lorem ipsum|your project name|project title here|"
    r"describe your project|<!-- ?(add|write|fill) |coming soon|WIP\b|"
    r"create-react-app|npx create-|this project was bootstrapped)"
)

LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


@register("docs", "Documentation", "README completeness, placeholders, broken links")
def check_docs(project: Project, ctx: dict) -> Iterable[Finding]:
    findings: list[Finding] = []
    readme_path = project.find_name("README.md", "README.rst", "README.txt", "README")
    if readme_path is None:
        findings.append(Finding(
            "docs.no-readme", "critical", "No README",
            "The README is the landing page of the repository. Without it GitHub "
            "shows a bare file listing and nobody can tell what the project does.",
            fix="Create README.md with: one-line description, install, usage example, licence.",
        ))
        return findings

    rel = project.rel(readme_path)
    text = project.read(readme_path) or ""
    words = len(text.split())
    ctx["readme_words"] = words

    if words < 40:
        findings.append(Finding(
            "docs.readme-stub", "high", f"README is a stub ({words} words)",
            "Too short to explain what the project is, how to install it or how to run it.",
            path=rel, fix="Expand to at least: what it does, install command, one usage example.",
        ))
    elif words < 120:
        findings.append(Finding(
            "docs.readme-thin", "medium", f"README is thin ({words} words)",
            "Missing the detail a first-time user needs to get running.",
            path=rel, fix="Add a worked example with real input and real output.",
        ))

    lines = text.splitlines()
    for key, pattern in SECTION_HINTS.items():
        if not any(re.search(pattern, ln) for ln in lines):
            sev = "medium" if key in ("install", "usage") else "low"
            findings.append(Finding(
                f"docs.missing-{key}", sev, f"README has no {key} section",
                f"Readers have to guess the {key} steps.",
                path=rel, fix=f"Add a `## {key.capitalize()}` heading with the concrete steps.",
            ))

    if not re.search(r"```", text) and words > 60:
        findings.append(Finding(
            "docs.no-code-example", "medium", "README contains no code block",
            "No copy-pasteable command or snippet, so adoption depends on reading source.",
            path=rel, fix="Add a fenced code block showing the exact command to run.",
        ))

    for i, line in enumerate(lines, 1):
        if PLACEHOLDER_TEXT.search(line):
            findings.append(Finding(
                "docs.placeholder", "medium", "Placeholder text left in the README",
                f"Line reads: {line.strip()[:90]}",
                path=rel, line=i, fix="Replace it with real content or delete the line.",
            ))

    # broken relative links / images
    for m in LINK.finditer(text):
        target = m.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#", "//")):
            continue
        clean = target.split("#")[0].split("?")[0]
        if not clean:
            continue
        candidate = (readme_path.parent / clean).resolve()
        if not candidate.exists():
            line = text.count("\n", 0, m.start()) + 1
            findings.append(Finding(
                "docs.broken-link", "medium", f"Broken relative link: {target}",
                "The target does not exist in the repository, so it 404s on GitHub.",
                path=rel, line=line, fix="Fix the path or remove the link.",
            ))

    if not project.find_name("CONTRIBUTING.md", "CONTRIBUTING.rst", ".github/CONTRIBUTING.md"):
        findings.append(Finding(
            "docs.no-contributing", "low", "No CONTRIBUTING guide",
            "Contributors do not know how to set up, test or format their change.",
            fix="Add CONTRIBUTING.md with dev setup, test command and PR expectations.",
        ))
    if not project.find_name("CHANGELOG.md", "CHANGES.md", "HISTORY.md"):
        findings.append(Finding(
            "docs.no-changelog", "info", "No CHANGELOG",
            "Users cannot tell what changed between versions.",
            fix="Add CHANGELOG.md following keepachangelog.com.",
        ))

    # Python public API docstrings
    py = [p for p in project.python_files() if "test" not in project.rel(p)]
    if py:
        import ast
        undocumented = 0
        total = 0
        first = None
        for path in py[:200]:
            src = project.read(path)
            if src is None:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name.startswith("_"):
                        continue
                    total += 1
                    if not ast.get_docstring(node):
                        undocumented += 1
                        if first is None:
                            first = (project.rel(path), node.lineno, node.name)
        if total >= 8 and undocumented / total > 0.6 and first:
            findings.append(Finding(
                "docs.no-docstrings", "low",
                f"{undocumented}/{total} public functions and classes have no docstring",
                f"For example `{first[2]}`. Nothing explains the contract of the public API.",
                path=first[0], line=first[1],
                fix="Add a one-line docstring to each public function, starting with a verb.",
            ))
    return findings
