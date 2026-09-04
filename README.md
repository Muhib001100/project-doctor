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
git clone https://github.com/OWNER/project-doctor.git
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

Critical findings bypass the category cap, because a leaked key or a file that
does not parse should always move the number.

Grades: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, otherwise F.

### Calibration, honestly

Real numbers from `--offline` scans of well-known repositories:

| Repository | Score | Critical | High | Medium | Low |
| --- | --- | --- | --- | --- | --- |
| project-doctor (this repo) | 87 | 0 | 0 | 10 | 9 |
| pallets/flask | 62 | 0 | 2 | 44 | 26 |
| psf/requests | 53 | 0 | 1 | 39 | 30 |
| tiangolo/fastapi | 33 | 1 | 8 | 58 | 154 |
| django/django | 0 | 2 | 29 | 994 | 691 |

Read that table as a warning about the score, not about Django. Large mature
codebases accumulate enough low-severity findings to saturate every cap, so the
number is most meaningful on small and mid-sized projects. On anything big,
ignore the grade and read the `critical` and `high` sections — those are the
ones tuned to be worth acting on.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports with the repo URL that
triggered a false positive are especially useful.

## License

MIT — see [LICENSE](LICENSE).
