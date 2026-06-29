from __future__ import annotations

import typer

from learnit_study import auth, courses, downloader, flashcards, notes


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
def courses_list() -> None:
    """Placeholder for listing current LearnIT courses."""
    typer.echo(courses.list_courses())


@course_app.command("download")
def course_download(
    course: str = typer.Option(..., "--course", help="LearnIT course id."),
) -> None:
    """Placeholder for downloading course materials."""
    typer.echo(downloader.download_course(course_id=course))


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
