#!/usr/bin/env python3
"""One-time setup: put your GitHub username and name into the project files.

Run this once after unzipping, before the first push:

    python configure.py

It rewrites the placeholder owner in pyproject.toml, README.md and
CONTRIBUTING.md, and the copyright line in LICENSE. Safe to run twice.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CURRENT_OWNER = "Not-Muhib"
CURRENT_NAME = "Muhammad Ansar"
OWNER_FILES = ["pyproject.toml", "README.md", "CONTRIBUTING.md"]


def find_current_owner() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"github\.com/([^/]+)/project-doctor", text)
    return m.group(1) if m else CURRENT_OWNER


def find_current_name() -> str:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    m = re.search(r"Copyright \(c\) \d{4} (.+)", text)
    return m.group(1).strip() if m else CURRENT_NAME


def ask(prompt: str, default: str) -> str:
    try:
        answer = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def main() -> int:
    old_owner = find_current_owner()
    old_name = find_current_name()

    print("project-doctor setup\n")
    owner = ask("GitHub username (exactly as it appears in your profile URL)", old_owner)
    name = ask("Name for the LICENSE copyright line", old_name)

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})?", owner):
        print(f"error: {owner!r} is not a valid GitHub username", file=sys.stderr)
        return 1

    changed = []
    for filename in OWNER_FILES:
        path = ROOT / filename
        text = path.read_text(encoding="utf-8")
        new = text.replace(f"github.com/{old_owner}/", f"github.com/{owner}/")
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(filename)

    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    new = re.sub(r'authors = \[\{ name = "[^"]*"', f'authors = [{{ name = "{name}"', text)
    if new != text:
        pyproject.write_text(new, encoding="utf-8")
        if "pyproject.toml" not in changed:
            changed.append("pyproject.toml")

    licence = ROOT / "LICENSE"
    text = licence.read_text(encoding="utf-8")
    new = re.sub(r"(Copyright \(c\) \d{4} ).+", rf"\g<1>{name}", text)
    if new != text:
        licence.write_text(new, encoding="utf-8")
        changed.append("LICENSE")

    print("\nupdated: " + (", ".join(changed) if changed else "nothing (already set)"))
    print("\nNext:")
    print("  git add -A")
    print('  git commit -m "Set repository owner"')
    print(f"  git remote add origin https://github.com/{owner}/project-doctor.git")
    print("  git push -u origin main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
