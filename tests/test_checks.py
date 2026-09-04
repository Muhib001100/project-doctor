
from project_doctor.checks.ci import check_ci
from project_doctor.checks.config import check_config
from project_doctor.checks.dependencies import check_dependencies, normalize, parse_requirements
from project_doctor.checks.docs import check_docs
from project_doctor.checks.quality import check_quality, complexity
from project_doctor.checks.tests import check_tests
from project_doctor.model import Project


def make(tmp_path, files: dict) -> Project:
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Project(tmp_path)


def ids(findings):
    return {f.check for f in findings}


# --- dependencies ----------------------------------------------------------
def test_normalize():
    assert normalize("Flask_SQL.Alchemy") == "flask-sql-alchemy"


def test_parse_requirements_skips_comments_and_flags():
    rows = parse_requirements("# c\n-r other.txt\nrequests==2.31.0\nflask\n")
    assert [r[1] for r in rows] == ["requests", "flask"]


def test_undeclared_import_is_flagged(tmp_path):
    project = make(tmp_path, {
        "app.py": "import requests\nimport os\n",
        "requirements.txt": "flask==3.0.0\n",
    })
    assert "deps.undeclared" in ids(check_dependencies(project, {}))


def test_declared_import_is_not_flagged(tmp_path):
    project = make(tmp_path, {
        "app.py": "import requests\n",
        "requirements.txt": "requests==2.31.0\n",
    })
    assert "deps.undeclared" not in ids(check_dependencies(project, {}))


def test_import_alias_map(tmp_path):
    project = make(tmp_path, {
        "app.py": "import yaml\n",
        "requirements.txt": "PyYAML==6.0.1\n",
    })
    assert "deps.undeclared" not in ids(check_dependencies(project, {}))


def test_unpinned_requirement(tmp_path):
    project = make(tmp_path, {"app.py": "x=1\n", "requirements.txt": "flask\n"})
    assert "deps.unpinned" in ids(check_dependencies(project, {}))


def test_local_module_import_not_flagged(tmp_path):
    project = make(tmp_path, {
        "requirements.txt": "flask==3.0.0\n",
        "mypkg/__init__.py": "",
        "mypkg/core.py": "x = 1\n",
        "app.py": "import mypkg\nfrom mypkg import core\n",
    })
    assert "deps.undeclared" not in ids(check_dependencies(project, {}))


def test_guarded_import_is_optional(tmp_path):
    project = make(tmp_path, {
        "requirements.txt": "flask==3.0.0\n",
        "app.py": "try:\n    import ujson\nexcept ImportError:\n    import json\n",
    })
    assert "deps.undeclared" not in ids(check_dependencies(project, {}))


def test_type_checking_import_is_optional(tmp_path):
    project = make(tmp_path, {
        "requirements.txt": "flask==3.0.0\n",
        "app.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import numpy\n",
    })
    assert "deps.undeclared" not in ids(check_dependencies(project, {}))


def test_docs_imports_are_ignored(tmp_path):
    project = make(tmp_path, {
        "requirements.txt": "flask==3.0.0\n",
        "docs/conf.py": "import sphinx_rtd_theme\n",
    })
    assert "deps.undeclared" not in ids(check_dependencies(project, {}))


def test_test_dir_undeclared_import_is_downgraded(tmp_path):
    project = make(tmp_path, {
        "requirements.txt": "flask==3.0.0\n",
        "tests/test_a.py": "import responses\n\n\ndef test_x():\n    assert responses\n",
    })
    found = [f for f in check_dependencies(project, {}) if f.check == "deps.undeclared"]
    assert found and found[0].severity == "medium"


# --- tests -----------------------------------------------------------------
def test_missing_tests_flagged(tmp_path):
    project = make(tmp_path, {f"m{i}.py": "x=1\n" for i in range(5)})
    assert "tests.none" in ids(check_tests(project, {}))


def test_assertless_test_flagged(tmp_path):
    project = make(tmp_path, {"tests/test_a.py": "def test_thing():\n    value = 1 + 1\n"})
    assert "tests.no-assert" in ids(check_tests(project, {}))


def test_asserting_test_not_flagged(tmp_path):
    project = make(tmp_path, {"tests/test_a.py": "def test_thing():\n    assert 1 + 1 == 2\n"})
    assert "tests.no-assert" not in ids(check_tests(project, {}))


# --- config ----------------------------------------------------------------
def test_missing_license_flagged(tmp_path):
    project = make(tmp_path, {"a.py": "x=1\n"})
    assert "config.no-license" in ids(check_config(project, {}))


def test_license_satisfies_check(tmp_path):
    project = make(tmp_path, {"a.py": "x=1\n", "LICENSE": "MIT\n"})
    assert "config.no-license" not in ids(check_config(project, {}))


def test_aws_key_detected(tmp_path):
    key = "AKIA" + "3F7QZLMN2VBXKD9P"  # project-doctor: ignore
    project = make(tmp_path, {"settings.py": f'KEY = "{key}"\n'})
    findings = [f for f in check_config(project, {}) if f.check == "config.secret"]
    assert findings and findings[0].severity in {"critical", "high", "medium"}


def test_example_looking_key_is_not_reported(tmp_path):
    project = make(tmp_path, {"settings.py": 'KEY = "AKIAIOSFODNN7EXAMPLE"\n'})
    assert not [f for f in check_config(project, {}) if f.check == "config.secret"]


def test_ignore_pragma_suppresses_secret(tmp_path):
    key = "AKIA" + "3F7QZLMN2VBXKD9P"  # project-doctor: ignore
    project = make(tmp_path, {"settings.py": f'KEY = "{key}"  # project-doctor: ignore\n'})
    assert not [f for f in check_config(project, {}) if f.check == "config.secret"]


def test_secret_in_tests_dir_is_downgraded(tmp_path):
    key = "AKIA" + "3F7QZLMN2VBXKD9P"  # project-doctor: ignore
    project = make(tmp_path, {"tests/test_x.py": f'KEY = "{key}"\n'})
    found = [f for f in check_config(project, {}) if f.check == "config.secret"]
    assert found and found[0].severity == "medium"


def test_placeholder_secret_ignored(tmp_path):
    project = make(tmp_path, {".env.example": 'API_KEY = "your-key-here"\n'})
    assert not [f for f in check_config(project, {})
                if f.check == "config.secret" and f.severity == "critical"]


def test_committed_env_flagged(tmp_path):
    project = make(tmp_path, {".env": "TOKEN=abc\n"})
    assert "config.env-committed" in ids(check_config(project, {}))


# --- docs ------------------------------------------------------------------
def test_missing_readme_is_critical(tmp_path):
    project = make(tmp_path, {"a.py": "x=1\n"})
    findings = list(check_docs(project, {}))
    assert findings[0].check == "docs.no-readme"
    assert findings[0].severity == "critical"


def test_broken_relative_link(tmp_path):
    project = make(tmp_path, {"README.md": "# T\n\nSee [docs](docs/guide.md).\n" + "word " * 200})
    assert "docs.broken-link" in ids(check_docs(project, {}))


def test_readme_stub_flagged(tmp_path):
    project = make(tmp_path, {"README.md": "# My project\n"})
    assert "docs.readme-stub" in ids(check_docs(project, {}))


# --- quality ---------------------------------------------------------------
def test_bare_except_flagged(tmp_path):
    project = make(tmp_path, {"a.py": "try:\n    pass\nexcept:\n    pass\n"})
    found = ids(check_quality(project, {}))
    assert "quality.bare-except" in found
    assert "quality.silent-except" in found


def test_mutable_default_flagged(tmp_path):
    project = make(tmp_path, {"a.py": "def f(items=[]):\n    return items\n"})
    assert "quality.mutable-default" in ids(check_quality(project, {}))


def test_eval_flagged(tmp_path):
    project = make(tmp_path, {"a.py": "def f(s):\n    return eval(s)\n"})
    assert "quality.eval" in ids(check_quality(project, {}))


def test_shell_true_flagged(tmp_path):
    project = make(tmp_path, {
        "a.py": "import subprocess\ndef f(c):\n    subprocess.run(c, shell=True)\n"
    })
    assert "quality.shell-true" in ids(check_quality(project, {}))


def test_syntax_error_is_critical(tmp_path):
    project = make(tmp_path, {"a.py": "def broken(:\n"})
    findings = [f for f in check_quality(project, {}) if f.check == "quality.syntax-error"]
    assert findings and findings[0].severity == "critical"


def test_complexity_counts_branches():
    import ast
    tree = ast.parse("def f(a):\n    if a:\n        for i in a:\n            pass\n")
    fn = tree.body[0]
    assert complexity(fn) >= 3


def test_clean_file_has_no_quality_findings(tmp_path):
    project = make(tmp_path, {"a.py": '"""Doc."""\n\n\ndef add(a, b):\n    return a + b\n'})
    assert not list(check_quality(project, {}))


# --- ci --------------------------------------------------------------------
def test_no_workflow_flagged(tmp_path):
    project = make(tmp_path, {"a.py": "x=1\n"})
    assert "ci.none" in ids(check_ci(project, {}))


def test_floating_action_ref_flagged(tmp_path):
    wf = "name: CI\non: [push, pull_request]\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@main\n      - run: pytest\n"
    project = make(tmp_path, {".github/workflows/ci.yml": wf})
    assert "ci.floating-action" in ids(check_ci(project, {}))


def test_outdated_action_flagged(tmp_path):
    wf = "on: [push, pull_request]\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@v2\n      - run: pytest\n"
    project = make(tmp_path, {".github/workflows/ci.yml": wf})
    assert "ci.outdated-action" in ids(check_ci(project, {}))


def test_pull_request_target_is_critical(tmp_path):
    wf = "on: pull_request_target\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n      - run: pytest\n"
    project = make(tmp_path, {".github/workflows/ci.yml": wf})
    findings = [f for f in check_ci(project, {}) if f.check == "ci.pr-target"]
    assert findings and findings[0].severity == "critical"


def test_missing_test_step_flagged(tmp_path):
    wf = "on: [push, pull_request]\npermissions:\n  contents: read\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n      - run: echo hi\n"
    project = make(tmp_path, {".github/workflows/ci.yml": wf})
    assert "ci.no-test-step" in ids(check_ci(project, {}))
