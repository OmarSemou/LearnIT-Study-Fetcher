from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from learnit_study import auth, courses
from learnit_study.cli import app


runner = CliRunner()


def local_tmp_path() -> Path:
    path = Path(".test_tmp") / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_cli_help_loads() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "learnit" in result.output.lower()


def test_auth_check_command_loads(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "check",
        lambda cookie=None: "LearnIT authentication succeeded. Cookie accepted and Moodle sesskey found.",
    )

    result = runner.invoke(app, ["auth", "check"])

    assert result.exit_code == 0
    assert "authentication succeeded" in result.output


def test_auth_check_cookie_option_takes_priority(monkeypatch) -> None:
    seen: dict[str, str | None] = {}
    monkeypatch.setenv("LEARNIT_COOKIE", "env-cookie")
    monkeypatch.chdir(local_tmp_path())
    Path("cookie.txt").write_text("file-cookie", encoding="utf-8")

    def fake_check(cookie=None):
        seen["cookie"] = cookie
        return "ok"

    monkeypatch.setattr(auth, "check", fake_check)

    result = runner.invoke(app, ["auth", "check", "--cookie", "cli-cookie"])

    assert result.exit_code == 0
    assert seen["cookie"] == "cli-cookie"


def test_courses_list_outputs_course_id_and_name(monkeypatch) -> None:
    seen: dict[str, courses.CourseClassification] = {}

    def fake_list_courses(
        cookie=None,
        classification=courses.CourseClassification.INPROGRESS,
        include_non_courses=False,
    ):
        seen["classification"] = classification
        return [
            courses.Course(
                id=3022795,
                shortname="BDSA",
                fullname="Analysis, Design and Software Architecture",
            )
        ]

    monkeypatch.setattr(
        courses,
        "list_courses",
        fake_list_courses,
    )

    result = runner.invoke(app, ["courses", "list"])

    assert result.exit_code == 0
    assert seen["classification"] == courses.CourseClassification.INPROGRESS
    assert "3022795" in result.output
    assert "Analysis, Design and Software Architecture" in result.output


def test_courses_list_all_uses_all_classification(monkeypatch) -> None:
    seen: dict[str, courses.CourseClassification] = {}

    def fake_list_courses(
        cookie=None,
        classification=courses.CourseClassification.INPROGRESS,
        include_non_courses=False,
    ):
        seen["classification"] = classification
        return []

    monkeypatch.setattr(courses, "list_courses", fake_list_courses)

    result = runner.invoke(app, ["courses", "list", "--all"])

    assert result.exit_code == 0
    assert seen["classification"] == courses.CourseClassification.ALL


def test_courses_list_classification_past_uses_past(monkeypatch) -> None:
    seen: dict[str, courses.CourseClassification] = {}

    def fake_list_courses(
        cookie=None,
        classification=courses.CourseClassification.INPROGRESS,
        include_non_courses=False,
    ):
        seen["classification"] = classification
        return []

    monkeypatch.setattr(courses, "list_courses", fake_list_courses)

    result = runner.invoke(app, ["courses", "list", "--classification", "past"])

    assert result.exit_code == 0
    assert seen["classification"] == courses.CourseClassification.PAST


def test_courses_list_rejects_all_and_classification_together() -> None:
    result = runner.invoke(app, ["courses", "list", "--all", "--classification", "past"])

    assert result.exit_code == 1
    assert "Use either --all or --classification, not both." in result.output


def test_courses_list_help_mentions_current_default_and_all_courses() -> None:
    result = runner.invoke(app, ["courses", "list", "--help"])

    assert result.exit_code == 0
    assert "current/in-progress" in result.output
    assert "StudyLab" in result.output
    assert "Show all enrolled" in result.output
    assert "including old" in result.output


def test_courses_list_include_non_courses_flag(monkeypatch) -> None:
    seen: dict[str, bool] = {}

    def fake_list_courses(
        cookie=None,
        classification=courses.CourseClassification.INPROGRESS,
        include_non_courses=False,
    ):
        seen["include_non_courses"] = include_non_courses
        return []

    monkeypatch.setattr(courses, "list_courses", fake_list_courses)

    result = runner.invoke(app, ["courses", "list", "--include-non-courses"])

    assert result.exit_code == 0
    assert seen["include_non_courses"] is True


def test_courses_list_all_and_include_non_courses_work_together(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_list_courses(
        cookie=None,
        classification=courses.CourseClassification.INPROGRESS,
        include_non_courses=False,
    ):
        seen["classification"] = classification
        seen["include_non_courses"] = include_non_courses
        return []

    monkeypatch.setattr(courses, "list_courses", fake_list_courses)

    result = runner.invoke(app, ["courses", "list", "--all", "--include-non-courses"])

    assert result.exit_code == 0
    assert seen["classification"] == courses.CourseClassification.ALL
    assert seen["include_non_courses"] is True
