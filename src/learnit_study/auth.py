from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests
from dotenv import load_dotenv


LEARNIT_MY_URL = "https://learnit.itu.dk/my/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 learnit-study-assistant/0.1"
)


class AuthError(RuntimeError):
    """Raised when LearnIT authentication cannot be completed safely."""


class HttpSession(Protocol):
    headers: requests.structures.CaseInsensitiveDict[str] | dict[str, str]

    def get(self, url: str, *, timeout: float) -> requests.Response:
        ...


@dataclass(frozen=True)
class AuthResult:
    sesskey: str


def load_cookie(cookie: str | None = None, cookie_file: Path | str = "cookie.txt") -> str:
    """Load a LearnIT cookie without printing or persisting it."""
    if cookie and cookie.strip():
        return cookie.strip()

    path = Path(cookie_file)
    if path.exists():
        file_cookie = path.read_text(encoding="utf-8").strip()
        if file_cookie:
            return file_cookie

    load_dotenv()
    env_cookie = os.getenv("LEARNIT_COOKIE", "").strip()
    if env_cookie:
        return env_cookie

    raise AuthError(
        "Missing LearnIT cookie. Provide --cookie, create cookie.txt, or set LEARNIT_COOKIE. "
        "The cookie may also be wrong or expired if authentication keeps failing."
    )


def build_session(cookie: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Cookie": cookie,
        }
    )
    return session


def extract_sesskey(html: str) -> str:
    patterns = [
        r'"sesskey"\s*:\s*"([^"]+)"',
        r"name=[\"']sesskey[\"']\s+value=[\"']([^\"']+)",
        r"sesskey=([A-Za-z0-9]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    raise AuthError(
        "LearnIT authentication failed: no Moodle sesskey was found. "
        "Your cookie may be missing, wrong, or expired."
    )


def authenticate(
    *,
    cookie: str | None = None,
    cookie_file: Path | str = "cookie.txt",
    session: HttpSession | None = None,
    timeout: float = 30.0,
) -> AuthResult:
    loaded_cookie = load_cookie(cookie=cookie, cookie_file=cookie_file)
    active_session = session or build_session(loaded_cookie)
    active_session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Cookie": loaded_cookie,
        }
    )

    try:
        response = active_session.get(LEARNIT_MY_URL, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AuthError(
            "LearnIT authentication failed. The cookie may be missing, wrong, or expired."
        ) from exc

    return AuthResult(sesskey=extract_sesskey(response.text))


def check(cookie: str | None = None, cookie_file: Path | str = "cookie.txt") -> str:
    authenticate(cookie=cookie, cookie_file=cookie_file)
    return "LearnIT authentication succeeded. Cookie accepted and Moodle sesskey found."
