from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from learnit_study import auth, courses, extraction
from learnit_study.web import app as web_app


@pytest.fixture(autouse=True)
def clear_web_security_env(monkeypatch):
    monkeypatch.delenv(web_app.WEB_PASSWORD_ENV, raising=False)
    monkeypatch.delenv(web_app.WEB_SECRET_KEY_ENV, raising=False)
    monkeypatch.delenv(web_app.ai_notes.GEMINI_API_KEY_ENV, raising=False)


def make_client() -> TestClient:
    web_app.COOKIE_STORE.clear()
    web_app.JOBS.clear()
    return TestClient(web_app.app)


def local_tmp_path() -> Path:
    path = Path(".test_tmp") / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def authenticate_client(client: TestClient, cookie: str = "MoodleSession=test-cookie") -> None:
    web_app.COOKIE_STORE["test-session"] = cookie
    client.cookies.set(web_app.SESSION_COOKIE_NAME, "test-session")


def login_client(client: TestClient, password: str = "strong-password") -> None:
    response = client.post("/login", data={"password": password}, follow_redirects=False)
    assert response.status_code == 303


def wait_for_job(client: TestClient, location: str, *, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    response = client.get(location)
    while "running" in response.text or "queued" in response.text:
        if time.monotonic() > deadline:
            raise AssertionError(f"Job did not finish: {response.text}")
        time.sleep(0.01)
        response = client.get(location)
    return response


def test_home_page_loads() -> None:
    client = make_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "LearnIT Study Assistant" in response.text
    assert "LearnIT cookie" in response.text
    assert "live login credential" in response.text


def test_login_page_loads_when_password_enabled(monkeypatch) -> None:
    monkeypatch.setenv(web_app.WEB_PASSWORD_ENV, "strong-password")
    client = make_client()

    response = client.get("/login")

    assert response.status_code == 200
    assert "Login" in response.text
    assert "strong-password" not in response.text


def test_protected_routes_redirect_to_login_when_not_authenticated(monkeypatch) -> None:
    monkeypatch.setenv(web_app.WEB_PASSWORD_ENV, "strong-password")
    client = make_client()

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_wrong_password_fails_without_revealing_password(monkeypatch) -> None:
    monkeypatch.setenv(web_app.WEB_PASSWORD_ENV, "strong-password")
    client = make_client()

    response = client.post("/login", data={"password": "wrong-password"})

    assert response.status_code == 401
    assert "Invalid password" in response.text
    assert "strong-password" not in response.text
    assert "wrong-password" not in response.text


def test_correct_password_allows_access(monkeypatch) -> None:
    monkeypatch.setenv(web_app.WEB_PASSWORD_ENV, "strong-password")
    client = make_client()

    login_client(client)
    response = client.get("/")

    assert response.status_code == 200
    assert "LearnIT Study Assistant" in response.text
    assert "Logout" in response.text


def test_logout_removes_access(monkeypatch) -> None:
    monkeypatch.setenv(web_app.WEB_PASSWORD_ENV, "strong-password")
    client = make_client()

    login_client(client)
    logout_response = client.post("/logout", follow_redirects=False)
    protected_response = client.get("/", follow_redirects=False)

    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/login"
    assert protected_response.status_code == 303
    assert protected_response.headers["location"] == "/login"


def test_static_css_still_loads_when_password_enabled(monkeypatch) -> None:
    monkeypatch.setenv(web_app.WEB_PASSWORD_ENV, "strong-password")
    client = make_client()

    response = client.get("/static/style.css")

    assert response.status_code == 200
    assert "body" in response.text


def test_auth_check_does_not_echo_cookie(monkeypatch) -> None:
    client = make_client()
    secret = "MoodleSession=super-secret-cookie"

    def fake_check(cookie=None, cookie_file="cookie.txt"):
        raise auth.AuthError(f"Invalid credential {cookie}")

    monkeypatch.setattr(web_app.auth, "check", fake_check)

    response = client.post("/auth/check", data={"learnit_cookie": secret})

    assert response.status_code == 400
    assert "Invalid credential [REDACTED]" in response.text
    assert secret not in response.text


def test_web_secrets_do_not_appear_in_rendered_pages(monkeypatch, caplog) -> None:
    client = make_client()
    web_password = "strong-password"
    api_key = "gemini-secret-key"
    learnit_cookie = "MoodleSession=live-cookie"
    monkeypatch.setenv(web_app.WEB_PASSWORD_ENV, web_password)
    monkeypatch.setenv(web_app.ai_notes.GEMINI_API_KEY_ENV, api_key)

    def fake_check(cookie=None, cookie_file="cookie.txt"):
        raise auth.AuthError(f"Bad cookie {cookie} with {api_key} and {web_password}")

    monkeypatch.setattr(web_app.auth, "check", fake_check)
    login_client(client, web_password)

    response = client.post("/auth/check", data={"learnit_cookie": learnit_cookie})

    rendered_and_logs = response.text + "\n".join(record.getMessage() for record in caplog.records)
    assert response.status_code == 400
    assert learnit_cookie not in rendered_and_logs
    assert api_key not in rendered_and_logs
    assert web_password not in rendered_and_logs


def test_missing_cookie_shows_clean_error() -> None:
    client = make_client()

    response = client.post("/auth/check", data={"learnit_cookie": ""})

    assert response.status_code == 400
    assert "Paste a LearnIT browser cookie" in response.text


def test_courses_page_renders_mocked_course_list(monkeypatch) -> None:
    client = make_client()
    authenticate_client(client, "MoodleSession=course-cookie")
    seen: dict[str, object] = {}

    def fake_list_courses(cookie=None, include_non_courses=False, **kwargs):
        seen["cookie"] = cookie
        seen["include_non_courses"] = include_non_courses
        return [
            courses.Course(
                id=3025533,
                shortname="DBIS",
                fullname="Database and Information Systems Foundations",
                startdate=1767225600,
            )
        ]

    monkeypatch.setattr(web_app.courses, "list_courses", fake_list_courses)

    response = client.get("/courses?include_non_courses=true")

    assert response.status_code == 200
    assert seen["cookie"] == "MoodleSession=course-cookie"
    assert seen["include_non_courses"] is True
    assert "3025533" in response.text
    assert "Database and Information Systems Foundations" in response.text
    assert "MoodleSession=course-cookie" not in response.text


def test_course_page_renders_action_buttons() -> None:
    client = make_client()
    authenticate_client(client)

    response = client.get("/course/3025533")

    assert response.status_code == 200
    assert "Inspect course structure" in response.text
    assert "Download materials" in response.text
    assert "Extract text" in response.text
    assert "Generate local notes" in response.text
    assert "Gemini AI notes" in response.text


def test_job_creation_and_status_with_mocked_operation(monkeypatch) -> None:
    client = make_client()
    out = local_tmp_path() / "output"
    monkeypatch.setattr(web_app, "output_dir", lambda: out)

    def fake_extract_course_text(course=None, out="output", course_dir=None):
        return extraction.ExtractionSummary(
            course_dir=out / "3025533 - Demo",
            sections_processed=1,
            files_extracted=2,
            files_skipped=0,
            files_failed=0,
        )

    monkeypatch.setattr(web_app.extraction, "extract_course_text", fake_extract_course_text)

    response = client.post("/course/3025533/extract", follow_redirects=False)

    assert response.status_code == 303
    job_response = wait_for_job(client, response.headers["location"])
    assert job_response.status_code == 200
    assert "done" in job_response.text
    assert "files_extracted" in job_response.text
    assert "2" in job_response.text


def test_notes_viewer_lists_and_escapes_fake_markdown(monkeypatch) -> None:
    client = make_client()
    output = local_tmp_path() / "output"
    course_dir = output / "3025533 - Demo Course"
    notes_dir = course_dir / "Lecture 1" / "notes"
    ai_notes_dir = course_dir / "Lecture 1" / "AI notes"
    notes_dir.mkdir(parents=True)
    ai_notes_dir.mkdir(parents=True)
    (notes_dir / "intro.notes.md").write_text("# Intro\n\n<script>alert('x')</script>", encoding="utf-8")
    (ai_notes_dir / "intro.ai-notes.md").write_text("# AI Intro", encoding="utf-8")
    monkeypatch.setattr(web_app, "output_dir", lambda: output)

    response = client.get("/course/3025533/notes")
    selected = client.get("/course/3025533/notes?note=Lecture%201/notes/intro.notes.md")

    assert response.status_code == 200
    assert "intro.notes.md" in response.text
    assert "intro.ai-notes.md" in response.text
    assert selected.status_code == 200
    assert "&lt;script&gt;alert" in selected.text
    assert "<script>alert" not in selected.text


def test_protected_courses_page_requires_cookie() -> None:
    client = make_client()

    response = client.get("/courses")

    assert response.status_code == 401
    assert "No LearnIT cookie is available" in response.text
