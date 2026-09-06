# Project Doctor

A single-command health check for a codebase. Point it at a folder or a GitHub
repo and it tells you what is broken, missing or risky — undeclared imports,
outdated packages, absent tests, leaked secrets, README gaps, dangerous code
patterns and unsafe GitHub Actions workflows.

Zero runtime dependencies. Pure standard library, Python 3.9+.

```
$ project-doctor .

  Project Doctor  my-api
  /home/me/code/my-api

  Health ██████████████░░░░░░  71/100  grade C

  crit 1   high 3   med 6   low 4

  CRITICAL  (1)
    • No README
      The README is the landing page of the repository. Without it GitHub
      shows a bare file listing and nobody can tell what the project does.
      fix: Create README.md with: one-line description, install, usage, licence.
```

## Setup

If you just unzipped this, run the one-time setup first so the repository links
and the licence carry your details:

```bash
python configure.py
```

## Install

From PyPI:

```bash
pip install project-doctor
```

Run it once without installing:

```bash
pipx run project-doctor .
```

From source:

```bash
git clone https://github.com/Not-Muhib/project-doctor.git
cd project-doctor
pip install -e ".[dev]"
```

## Usage

```bash
project-doctor .                                  # scan the current folder
project-doctor ~/code/my-api                      # scan any local path
project-doctor --github psf/requests              # scan a public GitHub repo
project-doctor --github OWNER/private --token ... # private repo
project-doctor . --serve                          # open an HTML report in the browser
project-doctor . -f markdown -o report.md         # write a Markdown report
project-doctor . -f json | jq '.findings[0]'      # machine-readable output
project-doctor . --only deps,ci --verbose         # run selected checks only
project-doctor . --offline                        # no network calls at all
```

Useful flags:

| Flag | What it does |
| --- | --- |
| `--format {terminal,json,markdown,html}` | Output format. |
| `-o FILE` | Write the report to a file instead of stdout. |
| `--serve [--port N]` | Render HTML and serve it on `127.0.0.1`. |
| `--only IDS` / `--skip IDS` | Run or exclude specific checks. |
| `--min-severity LEVEL` | Hide anything below `critical/high/medium/low/info`. |
| `--fail-on LEVEL` | Exit code 1 if a finding is at or above `LEVEL`. |
| `--offline` | Skip every check that touches the network. |
| `--ignore GLOB` | Extra paths to skip (repeatable). |
| `--list-checks` | Print the check catalogue. |

## What it checks

| Id | Area | Examples of what it finds |
| --- | --- | --- |
| `deps` | Dependencies | Modules imported but never declared, unpinned or unbounded requirements, wildcard npm versions, missing lockfile, three overlapping manifests. |
| `outdated` | Outdated packages | Pinned versions compared against the live PyPI and npm registries, with major-version jumps ranked higher. |
| `tests` | Tests | No test files at all, a suite too thin for the codebase, tests that assert nothing, permanently skipped tests, no pytest or coverage config. |
| `config` | Configuration & hygiene | Committed AWS/GitHub/OpenAI keys, private keys, database URLs with passwords, a tracked `.env`, missing or incomplete `.gitignore`, committed caches and virtualenvs, missing `LICENSE`, files above 10 MB, packaging gaps in `pyproject.toml`. |
| `docs` | Documentation | Missing README, stub README, no install or usage section, no code example, leftover placeholder text, relative links that 404, undocumented public API. |
| `quality` | Code quality | Syntax errors, bare `except:`, exceptions swallowed with `pass`, `eval`/`exec`, `subprocess(..., shell=True)`, mutable default arguments, high cyclomatic complexity, deep nesting, oversized functions and files. |
| `ci` | GitHub Actions | No workflow, no `pull_request` trigger, actions pinned to a branch, outdated action majors, `pull_request_target` with a checkout, untrusted event data interpolated into shell, no test step, no `permissions:` block, no matrix, no Dependabot. |

Secret detection deliberately skips anything that looks like a placeholder
(`your-key-here`, `EXAMPLE`, `<token>`) so example files stay quiet.

## Scoring

The report opens with a score out of 100. Each finding deducts points by
severity — critical 20, high 7, medium 2.5, low 0.8, info 0 — with three
dampeners so one noisy check cannot dominate:

- repeats of the same check decay at 0.55× each time;
- a single check can remove at most 8 points;
- a whole category (`deps`, `tests`, `quality`, ...) can remove at most 15.

Findings split into two counting modes so that size is not itself a penalty:

- **Absolute** — the presence or absence of something the project should have,
  or a fact that is equally bad at any size: no LICENSE, no CI, a leaked key,
  a file that does not parse. Counted as-is.
- **Density** — things that accumulate with codebase size: long functions,
  complex functions, undeclared imports. Counted per thousand lines of Python,
  so a 500k-line project is not marked down for being large.

Critical findings bypass the category cap, because a leaked key or a file that
does not parse should always move the number.

Grades: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, otherwise F.

### Calibration, honestly

Real numbers from `--offline` scans of well-known repositories:

| Repository | Python lines | Score | Critical | High | Medium | Low |
| --- | --- | --- | --- | --- | --- | --- |
| project-doctor (this repo) | 2,676 | 89 B | 0 | 0 | 10 | 9 |
| pallets/flask | 18,345 | 81 B | 0 | 2 | 38 | 26 |
| psf/requests | 12,032 | 77 C | 0 | 1 | 39 | 30 |
| tiangolo/fastapi | 112,998 | 71 C | 1 | 1 | 58 | 154 |
| django/django | 525,966 | 51 F | 1 | 16 | 994 | 691 |

Django's grade is driven by real findings, not volume: a workflow that combines
`pull_request_target` with a checkout, several `exec()` call sites, and untrusted
event data interpolated into shell steps. Whether those are acceptable in a
project of that size and maturity is a judgement the tool does not make for you.

Read the `critical` and `high` sections first. Those are the tiers tuned to be
worth acting on; medium and low are maintenance backlog, not alarms.

## Using it in CI

Add this to any repository to block merges that introduce a critical problem:

```yaml
- name: Project health check
  run: |
    pip install project-doctor
    project-doctor . --offline --fail-on high
```

`--offline` keeps the job hermetic and fast; drop it if you also want the
outdated-package check.

## Extending it

A check is one function with a decorator. Drop a module in
`src/project_doctor/checks/`, import it in `checks/__init__.py`, and it appears
in `--list-checks` automatically:

```python
from . import register
from ..model import Finding, Project


@register("docker", "Docker", "Dockerfile problems")
def check_docker(project: Project, ctx: dict):
    text = project.read_name("Dockerfile")
    if text and ":latest" in text:
        yield Finding(
            "docker.latest-tag", "medium",
            "Base image pinned to :latest",
            "The image changes under you between builds.",
            path="Dockerfile",
            fix="Pin a digest or an explicit version tag.",
        )
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
project-doctor . --offline     # the tool scanning itself
```

## Publishing

If you cloned this before it was on GitHub, see [PUBLISHING.md](PUBLISHING.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports with the repo URL that
triggered a false positive are especially useful.

## License

MIT — see [LICENSE](LICENSE).
