#!/usr/bin/env python3
"""Set your details, verify the project, and push it to GitHub.

Run this once from inside the project folder:

    python publish.py

It will:
  1. ask for your GitHub username and the name for the LICENSE
  2. rewrite the repository links and the copyright line
  3. install the package and run the test suite
  4. create the GitHub repository and push, if the GitHub CLI is available
     and signed in; otherwise print the exact commands to finish by hand

Safe to run more than once. It never touches your credentials: authentication
is handled by the GitHub CLI or by git itself.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
OWNER_FILES = ("pyproject.toml", "README.md", "CONTRIBUTING.md", "PUBLISHING.md")
REPO = "project-doctor"
DESCRIPTION = "Scan a project or GitHub repo and report what is broken, missing or risky."
TOPICS = [
    "cli", "python", "static-analysis", "code-quality", "linter",
    "github-actions", "developer-tools", "devtools",
]


# --------------------------------------------------------------------------- io
def say(message: str) -> None:
    print(message, flush=True)


def step(number: int, message: str) -> None:
    say(f"\n[{number}/4] {message}")


def ask(prompt: str, default: str) -> str:
    try:
        answer = input(f"{prompt}\n  [{default}]: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=check)


# ------------------------------------------------------------------- current state
def current_owner() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"github\.com/([^/]+)/" + REPO, text)
    return match.group(1) if match else "YOURNAME"


def current_name() -> str:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    match = re.search(r"Copyright \(c\) \d{4} (.+)", text)
    return match.group(1).strip() if match else "Your Name"


# ----------------------------------------------------------------------- rewriting
def apply_details(owner: str, name: str) -> list[str]:
    """Write the owner into the repository links and the name into the LICENSE."""
    old_owner = current_owner()
    changed: list[str] = []

    for filename in OWNER_FILES:
        path = ROOT / filename
        if not path.exists():
            continue
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

    return changed


# ---------------------------------------------------------------------- verifying
def venv_python() -> Path:
    """Path to the interpreter inside the local .venv, whatever the platform."""
    if sys.platform == "win32":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def install_into(python: str) -> subprocess.CompletedProcess:
    return run([python, "-m", "pip", "install", "-e", ".[dev]"], check=False)


def verify() -> bool:
    python = sys.executable
    say("  installing (pip install -e '.[dev]') ...")
    install = install_into(python)

    # Debian, Ubuntu and Homebrew mark the system Python as externally managed
    # (PEP 668) and refuse the install. Build a local virtualenv instead of
    # telling the user to override the protection.
    if install.returncode != 0 and "externally-managed-environment" in (
        install.stderr + install.stdout
    ):
        say("  system Python is protected; creating a local .venv instead ...")
        created = run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=False)
        if created.returncode != 0 or not venv_python().exists():
            say("  could not create .venv:\n" + (created.stderr or created.stdout))
            say("  install python3-venv (Debian/Ubuntu: sudo apt install python3-venv)")
            return False
        python = str(venv_python())
        install = install_into(python)

    if install.returncode != 0:
        say("  install failed:\n" + (install.stderr or install.stdout))
        return False
    if python != sys.executable:
        say(f"  using {python}")
        say("  activate it later with:  source .venv/bin/activate")

    say("  running the test suite ...")
    tests = run([python, "-m", "pytest", "-q"], check=False)
    tail = (tests.stdout or tests.stderr).strip().splitlines()[-3:]
    for line in tail:
        say("  " + line)
    if tests.returncode != 0:
        return False

    scan = run([python, "-m", "project_doctor", ".", "--offline", "-f", "json"],
               check=False)
    if scan.returncode == 0:
        import json
        try:
            say(f"  self-scan: {json.loads(scan.stdout)['score']}/100")
        except ValueError:
            pass
    return True


# ------------------------------------------------------------------------ pushing
def gh_ready() -> bool:
    if shutil.which("gh") is None:
        return False
    return subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0


def commit_pending(message: str) -> None:
    run(["git", "add", "-A"], check=False)
    status = run(["git", "status", "--porcelain"], check=False)
    if status.stdout.strip():
        run(["git", "commit", "-m", message], check=False)


def push_with_gh(owner: str) -> bool:
    say(f"  creating https://github.com/{owner}/{REPO} ...")
    created = run(
        ["gh", "repo", "create", f"{owner}/{REPO}", "--public",
         "--description", DESCRIPTION, "--source", ".", "--remote", "origin", "--push"],
        check=False,
    )
    if created.returncode != 0:
        message = (created.stderr or created.stdout).strip()
        if "already exists" in message.lower():
            say("  repository already exists, pushing to it instead")
            run(["git", "remote", "remove", "origin"], check=False)
            run(["git", "remote", "add", "origin",
                 f"https://github.com/{owner}/{REPO}.git"], check=False)
            pushed = run(["git", "push", "-u", "origin", "main"], check=False)
            if pushed.returncode != 0:
                say("  push failed:\n" + (pushed.stderr or pushed.stdout))
                return False
        else:
            say("  could not create the repository:\n  " + message)
            return False

    run(["gh", "repo", "edit", f"{owner}/{REPO}",
         *sum((["--add-topic", t] for t in TOPICS), [])], check=False)
    say(f"\n  done: https://github.com/{owner}/{REPO}")
    say(f"  CI:   https://github.com/{owner}/{REPO}/actions")
    return True


def manual_instructions(owner: str) -> None:
    say("\nThe GitHub CLI is not installed or not signed in, so the last step is")
    say("yours. Two options.\n")
    say("Option A - install the GitHub CLI once, then re-run this script:")
    say("  https://cli.github.com  then:  gh auth login")
    say("\nOption B - do it by hand:")
    say("  1. Open https://github.com/new")
    say(f"  2. Repository name: {REPO}")
    say("  3. Choose Public. Leave README, .gitignore and license UNTICKED.")
    say("  4. Click Create repository.")
    say("  5. Back here, run:")
    say(f"       git remote add origin https://github.com/{owner}/{REPO}.git")
    say("       git push -u origin main")
    say("\n  If git asks for a password, use a personal access token instead:")
    say("  https://github.com/settings/tokens -> Generate new token (classic)")
    say("  -> tick 'repo' -> paste the token as the password.")


# --------------------------------------------------------------------------- main
def main() -> int:
    say("project-doctor: set up and publish\n")

    owner = ask("GitHub username (exactly as it appears in your profile URL)", current_owner())
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})?", owner):
        say(f"error: {owner!r} is not a valid GitHub username")
        return 1
    name = ask("Name for the LICENSE copyright line", current_name())

    step(1, "writing your details into the project")
    changed = apply_details(owner, name)
    say("  updated: " + (", ".join(changed) if changed else "nothing, already set"))

    step(2, "verifying the project")
    if not verify():
        say("\nStopping: the project does not pass its own tests on this machine.")
        say("Send the output above to whoever is helping you before pushing.")
        return 1

    step(3, "committing")
    commit_pending("Set repository owner")
    log = run(["git", "log", "--oneline", "-1"], check=False)
    say("  " + log.stdout.strip())

    step(4, "publishing to GitHub")
    if not gh_ready():
        manual_instructions(owner)
        return 0
    if not confirm(f"  Create the public repository {owner}/{REPO} and push?"):
        say("  skipped.")
        manual_instructions(owner)
        return 0
    return 0 if push_with_gh(owner) else 1


if __name__ == "__main__":
    raise SystemExit(main())
