from __future__ import annotations

import typer

from learnit_study import auth, courses, downloader, flashcards, notes, parser


app = typer.Typer(help="Local-first study assistant for ITU LearnIT/Moodle.")
auth_app = typer.Typer(help="Authentication helpers.")
courses_app = typer.Typer(help="List LearnIT courses.")
course_app = typer.Typer(help="Work with a selected LearnIT course.")
notes_app = typer.Typer(help="Generate local study notes.")
flashcards_app = typer.Typer(help="Generate flashcards.")


@auth_app.command("check")
def auth_check(
    cookie: str | None = typer.Option(
        None,
        "--cookie",
        help="LearnIT browser Cookie header value. Prefer cookie.txt or LEARNIT_COOKIE.",
    ),
) -> None:
    """Check whether a LearnIT cookie is available and valid."""
    try:
        typer.echo(auth.check(cookie=cookie))
    except auth.AuthError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@courses_app.command("list")
def courses_list(
    cookie: str | None = typer.Option(
        None,
        "--cookie",
        help="LearnIT browser Cookie header value. Prefer cookie.txt or LEARNIT_COOKIE.",
    ),
    all_courses: bool = typer.Option(
        False,
        "--all",
        help="Show all enrolled courses, including old courses.",
    ),
    classification: courses.CourseClassification | None = typer.Option(
        None,
        "--classification",
        help="Advanced Moodle timeline classification. Default: inprogress.",
    ),
    include_non_courses: bool = typer.Option(
        False,
        "--include-non-courses",
        help="Include StudyLab/non-course entries. Hidden by default.",
    ),
) -> None:
    """List real LearnIT courses. Defaults to current/in-progress courses and hides StudyLab."""
    try:
        if all_courses and classification is not None:
            raise courses.CourseError("Use either --all or --classification, not both.")
        selected_classification = classification or (
            courses.CourseClassification.ALL
            if all_courses
            else courses.CourseClassification.INPROGRESS
        )
        typer.echo(
            courses.format_courses(
                courses.list_courses(
                    cookie=cookie,
                    classification=selected_classification,
                    include_non_courses=include_non_courses,
                )
            )
        )
    except (auth.AuthError, courses.CourseError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@course_app.command("download")
def course_download(
    course: str = typer.Option(..., "--course", help="LearnIT course id."),
    out: str = typer.Option("output", "--out", help="Output directory for downloaded materials."),
    delay: float = typer.Option(0.0, "--delay", help="Delay in seconds between activities."),
    cookie: str | None = typer.Option(
        None,
        "--cookie",
        help="LearnIT browser Cookie header value. Prefer cookie.txt or LEARNIT_COOKIE.",
    ),
) -> None:
    """Download supported LearnIT course materials."""
    try:
        summary = downloader.download_course(course_id=course, out=out, delay=delay, cookie=cookie)
        typer.echo(downloader.format_summary(summary))
    except (auth.AuthError, parser.ParserError, downloader.DownloadError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@course_app.command("inspect")
def course_inspect(
    course: str = typer.Option(..., "--course", help="LearnIT course id."),
    cookie: str | None = typer.Option(
        None,
        "--cookie",
        help="LearnIT browser Cookie header value. Prefer cookie.txt or LEARNIT_COOKIE.",
    ),
) -> None:
    """Inspect sections and activities on a LearnIT course page."""
    try:
        typer.echo(parser.format_course_page(parser.inspect_course(course_id=course, cookie=cookie)))
    except (auth.AuthError, parser.ParserError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@notes_app.command("generate")
def notes_generate(
    course: str = typer.Option(..., "--course", help="LearnIT course id."),
    ai: bool = typer.Option(False, "--ai", help="Future option for explicit AI mode."),
    no_ai: bool = typer.Option(False, "--no-ai", help="Future option for local-only mode."),
) -> None:
    """Placeholder for generating study notes."""
    typer.echo(notes.generate(course_id=course, ai=ai, no_ai=no_ai))


@flashcards_app.command("generate")
def flashcards_generate(
    course: str = typer.Option(..., "--course", help="LearnIT course id."),
) -> None:
    """Placeholder for generating flashcards."""
    typer.echo(flashcards.generate(course_id=course))


app.add_typer(auth_app, name="auth")
app.add_typer(courses_app, name="courses")
app.add_typer(course_app, name="course")
app.add_typer(notes_app, name="notes")
app.add_typer(flashcards_app, name="flashcards")


def main() -> None:
    app()
