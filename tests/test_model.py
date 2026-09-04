from project_doctor.model import Finding, Project, Report


def test_score_starts_at_100():
    assert Report("p", "/tmp").score() == 100


def test_severity_lowers_score():
    r = Report("p", "/tmp")
    r.add(Finding("a", "critical", "boom"))
    assert r.score() == 80
    assert r.grade() == "B"


def test_repeated_findings_have_diminishing_weight():
    one = Report("p", "/tmp")
    one.add(Finding("a", "high", "x"))
    many = Report("p", "/tmp")
    for _ in range(10):
        many.add(Finding("a", "high", "x"))
    assert many.score() < one.score()
    assert many.score() >= 100 - 8  # capped per check


def test_info_findings_do_not_change_score():
    r = Report("p", "/tmp")
    r.add(Finding("a", "info", "fyi"))
    assert r.score() == 100


def test_category_cap_limits_one_weak_area():
    r = Report("p", "/tmp")
    for i in range(12):
        r.add(Finding(f"quality.rule{i}", "medium", "nit"))
    assert r.score() == 85  # 15-point category cap, not 12 x 2.5


def test_counts_and_sorting():
    r = Report("p", "/tmp")
    r.add(Finding("b", "low", "l"))
    r.add(Finding("a", "critical", "c"))
    assert r.counts()["critical"] == 1
    assert r.sorted_findings()[0].severity == "critical"


def test_finding_location():
    assert Finding("a", "low", "t", path="x.py", line=3).location() == "x.py:3"
    assert Finding("a", "low", "t", path="x.py").location() == "x.py"
    assert Finding("a", "low", "t").location() == ""


def test_project_ignores_noise(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("//\n")
    project = Project(tmp_path)
    rels = [project.rel(p) for p in project.files()]
    assert "src/app.py" in rels
    assert not any("node_modules" in r for r in rels)
