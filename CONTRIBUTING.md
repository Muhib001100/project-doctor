# Contributing

## Setup

```bash
git clone https://github.com/OWNER/project-doctor.git
cd project-doctor
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Adding a check

1. Create `src/project_doctor/checks/<name>.py`.
2. Decorate the function with `@register(id, name, description)`. Set
   `network=True` if it makes HTTP requests, so `--offline` can skip it.
3. Import the module in `checks/__init__.py:all_checks()`.
4. Add tests in `tests/test_checks.py` covering both the positive case and a
   clean project that must not trigger it.

Every `Finding` needs a concrete `fix`. "Consider improving this" is not a fix;
"Add `requires-python = \">=3.9\"` to [project]" is.

## Rules of thumb

- False positives are worse than missed findings. If a pattern is commonly
  intentional, either drop it or rank it `info`.
- No runtime dependencies in the package. Dev dependencies are fine.
- Severity means impact: `critical` = the project is broken or a secret is
  exposed; `high` = it will break for someone else; `medium` = real risk;
  `low` = style and maintainability; `info` = optional polish.

## Before opening a PR

```bash
ruff check .
pytest
project-doctor . --offline --fail-on critical
```
