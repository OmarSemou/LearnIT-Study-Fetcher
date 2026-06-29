from __future__ import annotations

from pathlib import Path

import pytest
import requests

from learnit_study import auth


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    def __init__(self, html: str) -> None:
        self.html = html
        self.headers: dict[str, str] = {}
        self.requested_url: str | None = None

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        self.requested_url = url
        return FakeResponse(self.html)


def test_cookie_can_be_loaded_from_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LEARNIT_COOKIE", "env-cookie")

    assert auth.load_cookie() == "env-cookie"


def test_cookie_can_be_loaded_from_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LEARNIT_COOKIE", raising=False)
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("file-cookie", encoding="utf-8")

    assert auth.load_cookie(cookie_file=cookie_file) == "file-cookie"


def test_cli_cookie_takes_priority_over_file_and_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEARNIT_COOKIE", "env-cookie")
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("file-cookie", encoding="utf-8")

    assert auth.load_cookie(cookie="cli-cookie", cookie_file=cookie_file) == "cli-cookie"


def test_missing_cookie_gives_clear_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LEARNIT_COOKIE", raising=False)

    with pytest.raises(auth.AuthError, match="Missing LearnIT cookie"):
        auth.load_cookie()


def test_sesskey_is_extracted_from_valid_html() -> None:
    html = '<html><script>window.M = {"sesskey":"abc123XYZ"};</script></html>'

    assert auth.extract_sesskey(html) == "abc123XYZ"


def test_authenticate_fetches_my_page_and_finds_sesskey(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LEARNIT_COOKIE", raising=False)
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("file-cookie", encoding="utf-8")
    session = FakeSession('<input type="hidden" name="sesskey" value="abc123">')

    result = auth.authenticate(cookie_file=cookie_file, session=session)

    assert result.sesskey == "abc123"
    assert session.requested_url == auth.LEARNIT_MY_URL
    assert session.headers["Cookie"] == "file-cookie"
    assert "Mozilla/5.0" in session.headers["User-Agent"]


def test_auth_fails_cleanly_if_no_sesskey_is_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LEARNIT_COOKIE", raising=False)
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("file-cookie", encoding="utf-8")
    session = FakeSession("<html>No sesskey here</html>")

    with pytest.raises(auth.AuthError, match="cookie may be missing, wrong, or expired"):
        auth.authenticate(cookie_file=cookie_file, session=session)
