from __future__ import annotations

import os
import secrets
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from learnit_study import ai_notes, auth, courses, downloader, extraction, notes, parser


PACKAGE_DIR = Path(__file__).parent
SESSION_COOKIE_NAME = "learnit_session"
DEFAULT_RENDER_OUTPUT_DIR = "/tmp/learnit-output"
DEFAULT_LOCAL_OUTPUT_DIR = "output"
WEB_PASSWORD_ENV = "LEARNIT_WEB_PASSWORD"
WEB_SECRET_KEY_ENV = "LEARNIT_WEB_SECRET_KEY"
WEB_AUTH_SESSION_KEY = "web_authenticated"
LOGIN_PATH = "/login"
PUBLIC_PATHS = {LOGIN_PATH, "/favicon.ico"}
PUBLIC_PREFIXES = ("/static/",)


@dataclass
class WebJob:
    id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    result_text: str | None = None
    result_data: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class NoteView:
    section: str
    kind: str
    name: str
    relative_path: str


COOKIE_STORE: dict[str, str] = {}
JOBS: dict[str, WebJob] = {}
JOB_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("LEARNIT_WEB_WORKERS", "2")))


def session_secret_key() -> str:
    secret = os.getenv(WEB_SECRET_KEY_ENV)
    if secret:
        return secret
    if os.getenv("RENDER") and os.getenv(WEB_PASSWORD_ENV, "").strip():
        raise RuntimeError(
            "LEARNIT_WEB_SECRET_KEY must be set when LEARNIT_WEB_PASSWORD is enabled in production."
        )
    if os.getenv(WEB_PASSWORD_ENV, "").strip():
        warnings.warn(
            "LEARNIT_WEB_SECRET_KEY is not set. Generated a temporary local-development session secret.",
            RuntimeWarning,
            stacklevel=2,
        )
    return secrets.token_urlsafe(32)


def password_protection_enabled() -> bool:
    return bool(os.getenv(WEB_PASSWORD_ENV, "").strip())


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def is_web_authenticated(request: Request) -> bool:
    return bool(request.session.get(WEB_AUTH_SESSION_KEY))


app = FastAPI(
    title="LearnIT Study Assistant",
    description="Web MVP for downloading LearnIT materials and generating study notes.",
)
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
templates.env.globals["password_protection_enabled"] = lambda: password_protection_enabled()


@app.middleware("http")
async def require_web_password(request: Request, call_next):
    if not password_protection_enabled() or is_public_path(request.url.path):
        return await call_next(request)
    if is_web_authenticated(request):
        return await call_next(request)
    return RedirectResponse(LOGIN_PATH, status_code=303)


app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret_key(),
    same_site="lax",
    https_only=bool(os.getenv("RENDER")),
)


def output_dir() -> Path:
    configured = os.getenv("LEARNIT_OUTPUT_DIR")
    if configured:
        return Path(configured)
    if os.getenv("RENDER"):
        return Path(DEFAULT_RENDER_OUTPUT_DIR)
    return Path(DEFAULT_LOCAL_OUTPUT_DIR)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_cookie(request: Request) -> str | None:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    return COOKIE_STORE.get(session_id)


def require_cookie(request: Request) -> str:
    cookie = session_cookie(request)
    if not cookie:
        raise HTTPException(
            status_code=401,
            detail="No LearnIT cookie is available for this browser session. Check authentication first.",
        )
    return cookie


def set_session_cookie(response: RedirectResponse, cookie: str) -> None:
    session_id = secrets.token_urlsafe(24)
    COOKIE_STORE[session_id] = cookie
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="lax",
        secure=False,
    )


def safe_error(exc: Exception, extra_secrets: list[str] | None = None) -> str:
    message = str(exc)
    for secret in [*COOKIE_STORE.values(), *(extra_secrets or [])]:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    api_key = os.getenv(ai_notes.GEMINI_API_KEY_ENV)
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    web_password = os.getenv(WEB_PASSWORD_ENV)
    if web_password:
        message = message.replace(web_password, "[REDACTED]")
    web_secret = os.getenv(WEB_SECRET_KEY_ENV)
    if web_secret:
        message = message.replace(web_secret, "[REDACTED]")
    return message


def render_error(request: Request, message: str, *, status_code: int = 400) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": message},
        status_code=status_code,
    )


def summary_to_dict(result: Any) -> dict[str, Any]:
    if is_dataclass(result):
        data = asdict(result)
    elif isinstance(result, dict):
        data = result
    else:
        return {}
    return {key: str(value) if isinstance(value, Path) else value for key, value in data.items()}


def course_page_to_dict(course_page: parser.CoursePage) -> dict[str, Any]:
    return {
        "course_id": course_page.course_id,
        "title": course_page.title,
        "sections": [
            {
                "name": section.name,
                "activities": [
                    {
                        "name": activity.name,
                        "type": activity.type,
                        "cmid": activity.cmid,
                        "url": activity.url,
                    }
                    for activity in section.activities
                ],
            }
            for section in course_page.sections
        ],
    }


def start_job(title: str, operation: Callable[[], tuple[str, Any]]) -> WebJob:
    job_id = secrets.token_urlsafe(12)
    job = WebJob(id=job_id, title=title, status="queued", created_at=now_iso(), updated_at=now_iso())
    with JOB_LOCK:
        JOBS[job_id] = job

    def run() -> None:
        with JOB_LOCK:
            job.status = "running"
            job.updated_at = now_iso()
        try:
            result_text, result = operation()
            with JOB_LOCK:
                job.status = "done"
                job.result_text = result_text
                job.result_data = summary_to_dict(result)
                job.updated_at = now_iso()
        except Exception as exc:  # Keep job errors on the status page, never in logs.
            with JOB_LOCK:
                job.status = "failed"
                job.error = safe_error(exc)
                job.updated_at = now_iso()

    EXECUTOR.submit(run)
    return job


def get_job(job_id: str) -> WebJob | None:
    with JOB_LOCK:
        return JOBS.get(job_id)


def resolve_downloaded_course(course_id: str) -> Path:
    return extraction.resolve_course_dir(course=course_id, out=output_dir())


def collect_note_files(course_dir: Path) -> list[NoteView]:
    views: list[NoteView] = []
    for section_dir in sorted(path for path in course_dir.iterdir() if path.is_dir()):
        for folder_name, kind in (("notes", "Local"), ("AI notes", "AI")):
            notes_dir = section_dir / folder_name
            if not notes_dir.exists():
                continue
            for note_file in sorted(notes_dir.glob("*.md")):
                views.append(
                    NoteView(
                        section=section_dir.name,
                        kind=kind,
                        name=note_file.name,
                        relative_path=note_file.relative_to(course_dir).as_posix(),
                    )
                )
    return views


def read_selected_note(course_dir: Path, note_path: str | None, notes_list: list[NoteView]) -> tuple[NoteView | None, str | None]:
    if not note_path:
        return None, None
    allowed = {note.relative_path: note for note in notes_list}
    selected = allowed.get(note_path)
    if selected is None:
        raise HTTPException(status_code=404, detail="Note file was not found.")
    content = (course_dir / selected.relative_path).read_text(encoding="utf-8", errors="replace")
    return selected, content


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return render_error(request, str(exc.detail), status_code=exc.status_code)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if password_protection_enabled() and is_web_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"password_enabled": password_protection_enabled()},
    )


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form("")):
    configured_password = os.getenv(WEB_PASSWORD_ENV, "")
    if not configured_password:
        request.session[WEB_AUTH_SESSION_KEY] = True
        return RedirectResponse("/", status_code=303)
    if not secrets.compare_digest(password, configured_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "password_enabled": True,
                "error": "Invalid password.",
            },
            status_code=401,
        )
    request.session[WEB_AUTH_SESSION_KEY] = True
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(LOGIN_PATH if password_protection_enabled() else "/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/auth/check", response_class=HTMLResponse)
def auth_check(request: Request, learnit_cookie: str = Form("")):
    cookie = learnit_cookie.strip()
    if not cookie:
        return render_error(request, "Paste a LearnIT browser cookie before checking authentication.")
    try:
        auth.check(cookie=cookie)
    except auth.AuthError as exc:
        return render_error(request, safe_error(exc, extra_secrets=[cookie]))
    response = RedirectResponse("/courses?auth=ok", status_code=303)
    set_session_cookie(response, cookie)
    return response


@app.get("/courses", response_class=HTMLResponse)
def courses_page(
    request: Request,
    include_non_courses: bool = Query(False),
    auth: str | None = Query(None),
) -> HTMLResponse:
    cookie = require_cookie(request)
    course_list = courses.list_courses(cookie=cookie, include_non_courses=include_non_courses)
    return templates.TemplateResponse(
        request,
        "courses.html",
        {
            "courses": course_list,
            "include_non_courses": include_non_courses,
            "auth_ok": auth == "ok",
        },
    )


@app.get("/course/{course_id}", response_class=HTMLResponse)
def course_page(request: Request, course_id: str):
    return templates.TemplateResponse(
        request,
        "course.html",
        {
            "course_id": course_id,
            "output_dir": output_dir(),
            "has_cookie": session_cookie(request) is not None,
        },
    )


@app.post("/course/{course_id}/inspect")
def inspect_course(request: Request, course_id: str):
    cookie = require_cookie(request)
    def operation() -> tuple[str, Any]:
        course_page = parser.inspect_course(course_id=course_id, cookie=cookie)
        return parser.format_course_page(course_page), course_page_to_dict(course_page)

    job = start_job(
        f"Inspect course {course_id}",
        operation,
    )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@app.post("/course/{course_id}/download")
def download_course(request: Request, course_id: str):
    cookie = require_cookie(request)

    def operation() -> tuple[str, Any]:
        summary = downloader.download_course(course_id=course_id, out=output_dir(), cookie=cookie)
        return downloader.format_summary(summary), summary

    job = start_job(f"Download course {course_id}", operation)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@app.post("/course/{course_id}/extract")
def extract_course(course_id: str):
    def operation() -> tuple[str, Any]:
        summary = extraction.extract_course_text(course=course_id, out=output_dir())
        return extraction.format_summary(summary), summary

    job = start_job(f"Extract text for course {course_id}", operation)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@app.post("/course/{course_id}/notes/local")
def local_notes(course_id: str):
    def operation() -> tuple[str, Any]:
        summary = notes.generate(course_id=course_id, out=output_dir(), ai=False, no_ai=True)
        return notes.format_summary(summary), summary

    job = start_job(f"Generate local notes for course {course_id}", operation)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@app.post("/course/{course_id}/notes/ai/estimate", response_class=HTMLResponse)
def estimate_ai_notes(
    request: Request,
    course_id: str,
    model: str = Form(ai_notes.DEFAULT_MODEL),
    detail_level: str = Form(ai_notes.DEFAULT_DETAIL_LEVEL),
    max_materials: str = Form(""),
) -> HTMLResponse:
    parsed_max = int(max_materials) if max_materials.strip() else None
    estimate = ai_notes.estimate_cost(
        course_id,
        out=output_dir(),
        model=model,
        detail_level=detail_level,
        max_materials=parsed_max,
    )
    return templates.TemplateResponse(
        request,
        "course.html",
        {
            "course_id": course_id,
            "output_dir": output_dir(),
            "has_cookie": session_cookie(request) is not None,
            "estimate": ai_notes.format_estimate(estimate),
        },
    )


@app.post("/course/{course_id}/notes/ai/generate")
def generate_ai_notes(
    request: Request,
    course_id: str,
    model: str = Form(ai_notes.DEFAULT_MODEL),
    detail_level: str = Form(ai_notes.DEFAULT_DETAIL_LEVEL),
    max_materials: str = Form("1"),
    requests_per_minute: int = Form(ai_notes.DEFAULT_REQUESTS_PER_MINUTE),
    confirm_full: str | None = Form(None),
):
    raw_max = max_materials.strip()
    parsed_max = int(raw_max) if raw_max else None
    if parsed_max is None and confirm_full != "yes":
        return render_error(
            request,
            "Full-course AI generation requires confirmation because extracted course text will be sent to Gemini.",
        )

    def operation() -> tuple[str, Any]:
        summary = ai_notes.generate_ai_notes(
            course_id,
            out=output_dir(),
            model=model,
            detail_level=detail_level,
            max_materials=parsed_max,
            requests_per_minute=requests_per_minute,
        )
        return notes.format_summary(
            notes.NotesSummary(
                course_dir=summary.course_dir,
                sections_processed=summary.sections_processed,
                notes_generated=summary.notes_generated,
                notes_skipped=summary.notes_skipped,
                sections_skipped=summary.sections_skipped,
                failures=summary.failures,
            )
        ), summary

    job = start_job(f"Generate Gemini AI notes for course {course_id}", operation)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job was not found. In-memory jobs disappear after restart.")
    return templates.TemplateResponse(request, "job.html", {"job": job})


@app.get("/course/{course_id}/notes", response_class=HTMLResponse)
def notes_viewer(request: Request, course_id: str, note: str | None = Query(None)):
    course_dir = resolve_downloaded_course(course_id)
    note_files = collect_note_files(course_dir)
    selected, content = read_selected_note(course_dir, note, note_files)
    return templates.TemplateResponse(
        request,
        "notes.html",
        {
            "course_id": course_id,
            "course_dir": course_dir,
            "notes": note_files,
            "selected": selected,
            "content": content,
        },
    )
