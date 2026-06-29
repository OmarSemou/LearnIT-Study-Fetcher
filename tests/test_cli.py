from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from learnit_study import auth, courses, downloader, parser
from learnit_study.cli import app


runner = CliRunner()


def local_tmp_path() -> Path:
    path = Path(".test_tmp") / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_cli_help_loads() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "LearnIT Study Assistant" in result.output
    assert "Common workflow:" in result.output
    assert "Commands:" in result.output
    assert "Command flags:" in result.output
    assert "auth        Check LearnIT authentication" in result.output
    assert "notes       Generate local or Gemini AI notes" in result.output
    assert "course download" in result.output
    assert "required: --course" in result.output
    assert "optional: --out, --delay, --cookie" in result.output
    assert "notes generate" in result.output
    assert "modes: --no-ai, --ai" in result.output
    assert "ai: --provider, --model, --detail-level, --max-materials" in result.output
    assert "retry: --requests-per-minute, --retry-attempts, --retry-base-delay" in result.output
    assert "safety: --overwrite, --yes" in result.output
    assert "learnit-study <command> --help" in result.output
    assert "[default:" not in result.output


def test_root_help_short_alias_loads() -> None:
    result = runner.invoke(app, ["-h"])

    assert result.exit_code == 0
    assert "LearnIT Study Assistant" in result.output
    assert "Common workflow:" in result.output


def test_notes_generate_help_includes_ai_options() -> None:
    result = runner.invoke(app, ["notes", "generate", "--help"])

    assert result.exit_code == 0
    assert "Generate local notes by default" in result.output
    assert "Input/output options" in result.output
    assert "Local and AI mode options" in result.output
    assert "Rate limit and retry options" in result.output
    assert "Safety options" in result.output
    assert "--ai" in result.output
    assert "--provider" in result.output
    assert "--model" in result.output
    assert "--detail-level" in result.output
    assert "--requests-per-minute" in result.output
    assert "--retry-attempts" in result.output
    assert "--retry-base-delay" in result.output
    assert "--overwrite" in result.output
    assert "--yes" in result.output
    assert "learnit-study notes generate --course 3025533 --ai --max-materials 1" in result.output


def test_notes_generate_help_short_alias_loads() -> None:
    result = runner.invoke(app, ["notes", "generate", "-h"])

    assert result.exit_code == 0
    assert "--ai" in result.output


def test_notes_estimate_cost_help_includes_cost_options() -> None:
    result = runner.invoke(app, ["notes", "estimate-cost", "--help"])

    assert result.exit_code == 0
    assert "Estimate Gemini AI note generation cost" in result.output
    assert "--provider" in result.output
    assert "--model" in result.output
    assert "--detail-level" in result.output
    assert "--max-materials" in result.output
    assert "learnit-study notes" in result.output
    assert "estimate-cost --course 3025533" in result.output


def test_command_specific_help_keeps_course_options() -> None:
    result = runner.invoke(app, ["course", "download", "--help"])

    assert result.exit_code == 0
    assert "learnit-study course download --course 3025533" in result.output
    assert "--course" in result.output
    assert "--out" in result.output
    assert "--delay" in result.output
    assert "--cookie" in result.output


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


def test_course_inspect_output_contains_section_and_activity(monkeypatch) -> None:
    monkeypatch.setattr(
        parser,
        "inspect_course",
        lambda course_id, cookie=None: parser.CoursePage(
            course_id=course_id,
            sections=[
                parser.CourseSection(
                    name="Week 1 - Intro",
                    activities=[
                        parser.Activity(
                            name="Lecture slides",
                            type="file",
                            cmid=101,
                            url="https://learnit.itu.dk/mod/resource/view.php?id=101",
                            section_name="Week 1 - Intro",
                        )
                    ],
                )
            ],
        ),
    )

    result = runner.invoke(app, ["course", "inspect", "--course", "3025489"])

    assert result.exit_code == 0
    assert "Week 1 - Intro" in result.output
    assert "Lecture slides" in result.output
    assert "cmid=101" in result.output


def test_course_inspect_nested_output_contains_lecture_activity_without_parent_stealing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        parser,
        "inspect_course",
        lambda course_id, cookie=None: parser.CoursePage(
            course_id=course_id,
            sections=[
                parser.CourseSection(
                    name="1.Fundamentals of Information Systems",
                    activities=[
                        parser.Activity(
                            name="Course overview",
                            type="file",
                            cmid=10,
                            url="https://learnit.itu.dk/mod/resource/view.php?id=10",
                            section_name="1.Fundamentals of Information Systems",
                        )
                    ],
                ),
                parser.CourseSection(
                    name="Lecture 2: Information Systems in Global Business Today",
                    activities=[
                        parser.Activity(
                            name="Laudon chapter PDF",
                            type="file",
                            cmid=21,
                            url="https://learnit.itu.dk/mod/resource/view.php?id=21",
                            section_name="Lecture 2: Information Systems in Global Business Today",
                        )
                    ],
                ),
                parser.CourseSection(
                    name="Lecture 3: Information Systems, Organizations, and Strategy",
                    activities=[],
                ),
            ],
        ),
    )

    result = runner.invoke(app, ["course", "inspect", "--course", "3025533"])

    assert result.exit_code == 0
    assert "Lecture 2: Information Systems in Global Business Today" in result.output
    assert "Laudon chapter PDF" in result.output
    assert "Lecture 3: Information Systems, Organizations, and Strategy" not in result.output

    parent_block = result.output.split("Lecture 2: Information Systems in Global Business Today")[0]
    assert "1.Fundamentals of Information Systems" in parent_block
    assert "Laudon chapter PDF" not in parent_block


def test_course_inspect_real_like_output_uses_lecture_names_and_ignores_ui(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        parser,
        "inspect_course",
        lambda course_id, cookie=None: parser.CoursePage(
            course_id=course_id,
            sections=[
                parser.CourseSection(
                    name="Lecture 8: The Relational Model and Normalization",
                    activities=[
                        parser.Activity(
                            name="Chapter 3 PDF",
                            type="file",
                            cmid=81,
                            url="https://learnit.itu.dk/mod/resource/view.php?id=81",
                            section_name="Lecture 8: The Relational Model and Normalization",
                        )
                    ],
                ),
                parser.CourseSection(
                    name="Lecture 9: Database Design Using Normalization",
                    activities=[
                        parser.Activity(
                            name="Chapter 4 PDF",
                            type="file",
                            cmid=91,
                            url="https://learnit.itu.dk/mod/resource/view.php?id=91",
                            section_name="Lecture 9: Database Design Using Normalization",
                        )
                    ],
                ),
            ],
        ),
    )

    result = runner.invoke(app, ["course", "inspect", "--course", "3025533"])

    assert result.exit_code == 0
    assert "Lecture 8: The Relational Model and Normalization" in result.output
    assert "Lecture 9: Database Design Using Normalization" in result.output
    assert "Section 5 2" not in result.output
    assert "Collapse Expand" not in result.output


def test_course_download_does_not_print_cookie(monkeypatch) -> None:
    secret = "MoodleSession=super-secret"

    def fake_download_course(course_id, out="output", delay=0.0, cookie=None):
        assert cookie == secret
        return downloader.DownloadSummary(
            course_id=course_id,
            output_dir=Path("output") / course_id,
            files_downloaded=1,
            files_skipped=0,
            links_recorded=0,
            unsupported_skipped=0,
            failures=0,
        )

    monkeypatch.setattr(downloader, "download_course", fake_download_course)

    result = runner.invoke(app, ["course", "download", "--course", "3025533", "--cookie", secret])

    assert result.exit_code == 0
    assert secret not in result.output


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
