# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-05

### Added
- Seven checks: `deps`, `outdated`, `tests`, `config`, `docs`, `quality`, `ci`.
- Local directory and GitHub repository scanning (tarball download or `git clone`).
- Terminal, JSON, Markdown and HTML report formats, plus `--serve`.
- Weighted 0–100 health score with per-check decay and caps.
- `--fail-on` for use as a CI gate.
