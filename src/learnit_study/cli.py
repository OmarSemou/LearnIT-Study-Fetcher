from __future__ import annotations

import typer

from learnit_study import ai_notes, auth, courses, downloader, extraction, flashcards, notes, parser


HELP_CONTEXT = {"help_option_names": ["-h", "--help"]}

ROOT_HELP = """
LearnIT Study Assistant

Download LearnIT course materials, extract text, and generate study notes.

Common workflow:
  learnit-study auth check
  learnit-study courses list
  learnit-study course inspect --course 3025533
  learnit-study course download --course 3025533
  learnit-study text extract --course 3025533
  learnit-study notes generate --course 3025533
  learnit-study notes generate --course 3025533 --ai

Commands:
  auth        Check LearnIT authentication
  courses     List LearnIT courses
  course      Inspect or download a course
  text        Extract text from downloaded materials
  notes       Generate local or Gemini AI notes
  flashcards  Placeholder for future flashcards

Command flags:
  auth check
    optional: --cookie

  courses list
    optional: --cookie, --all, --classification, --include-non-courses

  course inspect
    required: --course
    optional: --cookie

  course download
    required: --course
    optional: --out, --delay, --cookie

  text extract
    use: --course or --course-dir
    optional: --out

  notes generate
    use: --course or --course-dir
    modes: --no-ai, --ai
    ai: --provider, --model, --detail-level, --max-materials
    retry: --requests-per-minute, --retry-attempts, --retry-base-delay
    safety: --overwrite, --yes

  notes estimate-cost
    use: --course or --course-dir
    optional: --out, --provider, --model, --detail-level, --max-materials

  flashcards generate
    required: --course

Use:
  learnit-study <command> --help
for detailed option descriptions and defaults.
""".strip()

NOTES_GENERATE_HELP = """[pre]
Default mode is local and free:
  learnit-study notes generate --course 3025533

Gemini AI mode sends extracted text to Gemini only when --ai is passed:
  learnit-study notes generate --course 3025533 --ai --max-materials 1
  learnit-study notes generate --course 3025533 --ai --provider gemini --model gemini-3.1-flash-lite --requests-per-minute 10

Local notes are saved under notes/. Gemini AI notes are saved under AI notes/.
[/pre]""".strip()

NOTES_ESTIMATE_HELP = """[pre]
Estimate Gemini API cost without making API calls:
  learnit-study notes estimate-cost --course 3025533
  learnit-study notes estimate-cost --course 3025533 --provider gemini --model gemini-3.1-flash-lite --detail-level exam
[/pre]""".strip()

COURSE_DOWNLOAD_HELP = """[pre]
Examples:
  learnit-study course download --course 3025533
  learnit-study course download --course 3025533 --out output --delay 0.5

Downloaded files are saved locally under the output directory.
[/pre]""".strip()

INPUT_OUTPUT_PANEL = "Input/output options"
LOCAL_AI_PANEL = "Local and AI mode options"
RATE_LIMIT_PANEL = "Rate limit and retry options"
SAFETY_PANEL = "Safety options"


app = typer.Typer(
    help="Download LearnIT course materials, extract text, and generate study notes.",
    context_settings=HELP_CONTEXT,
    add_completion=False,
    invoke_without_command=True,
    add_help_option=False,
)
auth_app = typer.Typer(help="Check LearnIT authentication.", context_settings=HELP_CONTEXT)
courses_app = typer.Typer(help="List LearnIT courses.", context_settings=HELP_CONTEXT)
course_app = typer.Typer(help="Inspect or download a course.", context_settings=HELP_CONTEXT)
notes_app = typer.Typer(help="Generate local or Gemini AI notes.", context_settings=HELP_CONTEXT)
flashcards_app = typer.Typer(help="Placeholder for future flashcards.", context_settings=HELP_CONTEXT)
text_app = typer.Typer(help="Extract text from downloaded materials.", context_settings=HELP_CONTEXT)


@app.callback()
def root(
    ctx: typer.Context,
    help_requested: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
) -> None:
    """Show a short root help page or dispatch to a command group."""
    if help_requested or ctx.invoked_subcommand is None:
        typer.echo(ROOT_HELP)
        raise typer.Exit()


@auth_app.command("check", context_settings=HELP_CONTEXT)
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


@courses_app.command("list", context_settings=HELP_CONTEXT)
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


@course_app.command(
    "download",
    help="Download supported LearnIT course materials.",
    epilog=COURSE_DOWNLOAD_HELP,
    context_settings=HELP_CONTEXT,
)
def course_download(
    course: str = typer.Option(..., "--course", help="LearnIT course id.", rich_help_panel=INPUT_OUTPUT_PANEL),
    out: str = typer.Option(
        "output",
        "--out",
        help="Output directory for downloaded materials.",
        rich_help_panel=INPUT_OUTPUT_PANEL,
    ),
    delay: float = typer.Option(
        0.0,
        "--delay",
        help="Delay in seconds between activities.",
        rich_help_panel=SAFETY_PANEL,
    ),
    cookie: str | None = typer.Option(
        None,
        "--cookie",
        help="LearnIT browser Cookie header value. Prefer cookie.txt or LEARNIT_COOKIE.",
        rich_help_panel=SAFETY_PANEL,
    ),
) -> None:
    """Download supported LearnIT course materials."""
    try:
        summary = downloader.download_course(course_id=course, out=out, delay=delay, cookie=cookie)
        typer.echo(downloader.format_summary(summary))
    except (auth.AuthError, parser.ParserError, downloader.DownloadError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@course_app.command("inspect", context_settings=HELP_CONTEXT)
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


@text_app.command("extract", context_settings=HELP_CONTEXT)
def text_extract(
    course: str | None = typer.Option(None, "--course", help="LearnIT course id."),
    out: str = typer.Option("output", "--out", help="Output directory containing downloaded courses."),
    course_dir: str | None = typer.Option(None, "--course-dir", help="Exact downloaded course folder."),
) -> None:
    """Extract text from already-downloaded local course materials."""
    try:
        summary = extraction.extract_course_text(course=course, out=out, course_dir=course_dir)
        typer.echo(extraction.format_summary(summary))
    except extraction.ExtractionError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@notes_app.command(
    "generate",
    help="Generate local notes by default, or Gemini AI notes with --ai.",
    epilog=NOTES_GENERATE_HELP,
    context_settings=HELP_CONTEXT,
)
def notes_generate(
    course: str | None = typer.Option(
        None,
        "--course",
        help="LearnIT course id.",
        rich_help_panel=INPUT_OUTPUT_PANEL,
    ),
    out: str = typer.Option(
        "output",
        "--out",
        help="Output directory containing downloaded courses.",
        rich_help_panel=INPUT_OUTPUT_PANEL,
    ),
    course_dir: str | None = typer.Option(
        None,
        "--course-dir",
        help="Exact downloaded course folder.",
        rich_help_panel=INPUT_OUTPUT_PANEL,
    ),
    ai: bool = typer.Option(False, "--ai", help="Enable explicit Gemini AI mode.", rich_help_panel=LOCAL_AI_PANEL),
    no_ai: bool = typer.Option(True, "--no-ai", help="Use local non-AI note generation.", rich_help_panel=LOCAL_AI_PANEL),
    provider: str = typer.Option(
        ai_notes.DEFAULT_PROVIDER,
        "--provider",
        help="AI provider. Currently: gemini.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
    model: str = typer.Option(
        ai_notes.DEFAULT_MODEL,
        "--model",
        help="Gemini model to use.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
    detail_level: str = typer.Option(
        ai_notes.DEFAULT_DETAIL_LEVEL,
        "--detail-level",
        help="AI note depth. Use exam for detailed exam-prep notes or standard for shorter notes.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
    max_materials: int | None = typer.Option(
        None,
        "--max-materials",
        min=1,
        help="Limit AI generation to the first N extracted materials for safe testing.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
    requests_per_minute: int = typer.Option(
        ai_notes.DEFAULT_REQUESTS_PER_MINUTE,
        "--requests-per-minute",
        min=1,
        help="Throttle Gemini API calls to this many requests per minute.",
        rich_help_panel=RATE_LIMIT_PANEL,
    ),
    retry_attempts: int = typer.Option(
        ai_notes.DEFAULT_RETRY_ATTEMPTS,
        "--retry-attempts",
        min=1,
        help="Maximum attempts for rate-limited Gemini requests.",
        rich_help_panel=RATE_LIMIT_PANEL,
    ),
    retry_base_delay: float = typer.Option(
        ai_notes.DEFAULT_RETRY_BASE_DELAY,
        "--retry-base-delay",
        min=0.0,
        help="Base delay in seconds for exponential rate-limit backoff.",
        rich_help_panel=RATE_LIMIT_PANEL,
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Regenerate existing non-empty AI note files.",
        rich_help_panel=SAFETY_PANEL,
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip AI privacy/cost confirmation prompt.",
        rich_help_panel=SAFETY_PANEL,
    ),
) -> None:
    """Generate local study notes from per-material extracted files."""
    try:
        if ai:
            estimate = ai_notes.estimate_cost(
                course,
                course_dir=course_dir,
                out=out,
                provider=provider,
                model=model,
                detail_level=detail_level,
                max_materials=max_materials,
                overwrite=overwrite,
            )
            typer.echo(ai_notes.format_estimate(estimate))
            typer.echo()
            typer.echo("You are about to send extracted course text to the Gemini API.")
            typer.echo("Free-tier Gemini API usage may be used to improve Google products.")
            typer.echo("Paid-tier Gemini API usage is not used to improve Google products.")
            typer.echo("Do not use AI mode for sensitive or private material unless you understand this.")
            typer.echo(
                "Gemini free-tier full-course generation may take several minutes because requests are throttled."
            )
            if not yes and not typer.confirm("Continue?", default=False):
                typer.echo("Aborted. No API calls were made.")
                raise typer.Exit(0)
        summary = notes.generate(
            course_id=course,
            course_dir=course_dir,
            out=out,
            ai=ai,
            no_ai=no_ai,
            provider=provider,
            model=model,
            detail_level=detail_level,
            max_materials=max_materials,
            requests_per_minute=requests_per_minute,
            retry_attempts=retry_attempts,
            retry_base_delay=retry_base_delay,
            overwrite=overwrite,
            progress=typer.echo if ai else None,
        )
        typer.echo(notes.format_summary(summary))
    except (notes.NotesError, ai_notes.AINotesError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@notes_app.command(
    "estimate-cost",
    help="Estimate Gemini AI note generation cost without making API calls.",
    epilog=NOTES_ESTIMATE_HELP,
    context_settings=HELP_CONTEXT,
)
def notes_estimate_cost(
    course: str | None = typer.Option(
        None,
        "--course",
        help="LearnIT course id.",
        rich_help_panel=INPUT_OUTPUT_PANEL,
    ),
    out: str = typer.Option(
        "output",
        "--out",
        help="Output directory containing downloaded courses.",
        rich_help_panel=INPUT_OUTPUT_PANEL,
    ),
    course_dir: str | None = typer.Option(
        None,
        "--course-dir",
        help="Exact downloaded course folder.",
        rich_help_panel=INPUT_OUTPUT_PANEL,
    ),
    provider: str = typer.Option(
        ai_notes.DEFAULT_PROVIDER,
        "--provider",
        help="AI provider. Currently: gemini.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
    model: str = typer.Option(
        ai_notes.DEFAULT_MODEL,
        "--model",
        help="Gemini model to estimate.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
    detail_level: str = typer.Option(
        ai_notes.DEFAULT_DETAIL_LEVEL,
        "--detail-level",
        help="AI note depth for cost estimate: exam or standard.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
    max_materials: int | None = typer.Option(
        None,
        "--max-materials",
        min=1,
        help="Estimate only the first N extracted materials.",
        rich_help_panel=LOCAL_AI_PANEL,
    ),
) -> None:
    """Estimate Gemini AI note generation cost without making API calls."""
    try:
        estimate = ai_notes.estimate_cost(
            course,
            course_dir=course_dir,
            out=out,
            provider=provider,
            model=model,
            detail_level=detail_level,
            max_materials=max_materials,
        )
        typer.echo(ai_notes.format_estimate(estimate))
    except (ai_notes.AINotesError, extraction.ExtractionError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@flashcards_app.command("generate", context_settings=HELP_CONTEXT)
def flashcards_generate(
    course: str = typer.Option(..., "--course", help="LearnIT course id."),
) -> None:
    """Placeholder for generating flashcards."""
    typer.echo(flashcards.generate(course_id=course))


app.add_typer(auth_app, name="auth")
app.add_typer(courses_app, name="courses")
app.add_typer(course_app, name="course")
app.add_typer(text_app, name="text")
app.add_typer(notes_app, name="notes")
app.add_typer(flashcards_app, name="flashcards")


def main() -> None:
    app()
