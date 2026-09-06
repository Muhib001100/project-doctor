import json

import pytest

from project_doctor.cli import main
from project_doctor.fetch import FetchError, parse_github
from project_doctor.model import Finding, Report
from project_doctor.report import render_html, render_json, render_markdown, render_terminal


@pytest.fixture()
def sample_report():
    r = Report("demo", "/tmp/demo")
    r.add(Finding("a.b", "high", "Something is wrong", "Because of X.",
                  path="src/a.py", line=12, fix="Do Y."))
    r.add(Finding("c.d", "low", "Minor thing"))
    return r


def test_render_json_roundtrip(sample_report):
    data = json.loads(render_json(sample_report))
    assert data["project"] == "demo"
    assert data["counts"]["high"] == 1
    assert data["findings"][0]["title"] == "Something is wrong"


def test_render_markdown(sample_report):
    md = render_markdown(sample_report)
    assert "# Project Doctor report: demo" in md
    assert "src/a.py:12" in md


def test_render_html_escapes(sample_report):
    sample_report.add(Finding("x", "medium", "<script>alert(1)</script>"))
    out = render_html(sample_report)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_render_terminal_plain(sample_report):
    text = render_terminal(sample_report, color=False)
    assert "\033[" not in text
    assert "Something is wrong" in text


def test_parse_github_forms():
    assert parse_github("psf/requests") == ("psf", "requests")
    assert parse_github("https://github.com/psf/requests") == ("psf", "requests")
    assert parse_github("https://github.com/psf/requests.git") == ("psf", "requests")
    with pytest.raises(FetchError):
        parse_github("not a repo!!")


def test_cli_list_checks(capsys):
    assert main(["--list-checks"]) == 0
    assert "quality" in capsys.readouterr().out


def test_cli_json_output(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x = 1\n")
    assert main([str(tmp_path), "--offline", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert 0 <= data["score"] <= 100


def test_cli_fail_on(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x = 1\n")   # no README -> critical
    assert main([str(tmp_path), "--offline", "--fail-on", "critical"]) == 1


def test_cli_writes_file(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    out = tmp_path / "r.html"
    assert main([str(tmp_path), "--offline", "-f", "html", "-o", str(out)]) == 0
    assert "<!doctype html>" in out.read_text()


def test_cli_bad_path(capsys):
    assert main(["/nonexistent/path/xyz", "--offline"]) == 2


def test_cli_only_and_skip(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x = 1\n")
    main([str(tmp_path), "--offline", "--only", "docs", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert {f["check"].split(".")[0] for f in data["findings"]} <= {"docs"}


def test_min_severity_does_not_inflate_score(tmp_path, capsys):
    (tmp_path / "a.py").write_text("try:\n    pass\nexcept:\n    pass\n")
    main([str(tmp_path), "--offline", "-f", "json"])
    full = json.loads(capsys.readouterr().out)["score"]
    main([str(tmp_path), "--offline", "-f", "json", "--min-severity", "critical"])
    filtered = json.loads(capsys.readouterr().out)
    assert filtered["score"] == full
    assert all(f["severity"] == "critical" for f in filtered["findings"])


def test_no_check_raises_on_a_realistic_project(tmp_path):
    """A check that crashes is swallowed into report.errors; keep that at zero."""
    from project_doctor.model import Project
    from project_doctor.scanner import run

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n\n\ndef main():\n    return os.getcwd()\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_main():\n    assert True\n")
    (tmp_path / "README.md").write_text("# App\n\n## Install\n\n```\npip install app\n```\n")
    (tmp_path / "LICENSE").write_text("MIT\n")
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\n\n[project]\nname = "app"\n'
        'version = "0.1.0"\nrequires-python = ">=3.9"\n'
    )
    report = run(Project(tmp_path), offline=True)
    assert report.errors == []


def test_scanner_reports_a_broken_check_instead_of_crashing():
    from project_doctor import checks as checks_module
    from project_doctor.model import Project
    from project_doctor.scanner import run

    def boom(project, ctx):
        raise ValueError("bad check")

    original = checks_module.all_checks
    checks_module.all_checks = lambda: [checks_module.Check("boom", "Boom", "", boom)]
    try:
        report = run(Project("."), offline=True)
    finally:
        checks_module.all_checks = original
    assert any("boom" in e for e in report.errors)
