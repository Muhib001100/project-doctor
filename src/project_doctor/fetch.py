"""Fetch a GitHub repository into a temporary directory for scanning."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_REF = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)?"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})?)/"
    r"(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


class FetchError(RuntimeError):
    pass


def parse_github(ref: str) -> tuple[str, str]:
    m = GITHUB_REF.match(ref.strip())
    if not m:
        raise FetchError(f"not a GitHub repo reference: {ref!r} (expected owner/repo)")
    return m.group("owner"), m.group("repo")


def fetch_github(ref: str, branch: str | None = None, token: str | None = None) -> Path:
    """Download a repo tarball into a temp dir. Returns the extracted root."""
    owner, repo = parse_github(ref)
    dest = Path(tempfile.mkdtemp(prefix="project-doctor-"))
    branches = [branch] if branch else ["HEAD", "main", "master"]
    last: Exception | None = None
    for b in branches:
        url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{b}"
        headers = {"User-Agent": "project-doctor"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                blob = resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            continue
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            shutil.rmtree(dest, ignore_errors=True)
            raise FetchError(f"could not reach GitHub: {exc}") from exc
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            _safe_extract(tar, dest)
        entries = [p for p in dest.iterdir() if p.is_dir()]
        return entries[0] if len(entries) == 1 else dest
    shutil.rmtree(dest, ignore_errors=True)
    raise FetchError(
        f"could not download {owner}/{repo} ({last}). "
        "Private repo? Pass --token, or clone it and scan the local path."
    )


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract, refusing paths that escape dest (tarslip / CVE-2007-4559)."""
    root = dest.resolve()
    for member in tar.getmembers():
        target = (root / member.name).resolve()
        if not str(target).startswith(str(root)):
            raise FetchError(f"refusing unsafe tar path: {member.name}")
        if member.issym() or member.islnk():
            link = (target.parent / member.linkname).resolve()
            if not str(link).startswith(str(root)):
                raise FetchError(f"refusing unsafe link: {member.name}")
    if hasattr(tarfile, "data_filter"):
        tar.extractall(dest, filter="data")
    else:  # Python < 3.12
        tar.extractall(dest)  # noqa: S202 - every member validated above


def clone_github(ref: str, branch: str | None = None) -> Path:
    """Shallow-clone with git. Used when --clone is passed."""
    owner, repo = parse_github(ref)
    dest = Path(tempfile.mkdtemp(prefix="project-doctor-"))
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [f"https://github.com/{owner}/{repo}.git", str(dest / repo)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except FileNotFoundError as exc:
        raise FetchError("git is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise FetchError(exc.stderr.decode("utf-8", "replace").strip()) from exc
    return dest / repo
