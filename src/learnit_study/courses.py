from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from html import unescape
from pathlib import Path
from typing import Any, Protocol

import requests

from learnit_study import auth


MOODLE_AJAX_URL = "https://learnit.itu.dk/lib/ajax/service.php"
COURSES_METHOD = "core_course_get_enrolled_courses_by_timeline_classification"
NON_COURSE_MARKERS = ("studylab", "study lab", "study-lab")


class CourseClassification(str, Enum):
    INPROGRESS = "inprogress"
    ALL = "all"
    PAST = "past"
    FUTURE = "future"


class CourseError(RuntimeError):
    """Raised when LearnIT course listing fails."""


class CourseSession(Protocol):
    def post(
        self,
        url: str,
        *,
        params: dict[str, str],
        json: list[dict[str, Any]],
        timeout: float,
    ) -> requests.Response:
        ...


@dataclass(frozen=True)
class Course:
    id: int
    shortname: str
    fullname: str
    startdate: int | None = None


def fetch_courses(
    session: CourseSession,
    *,
    sesskey: str,
    classification: CourseClassification = CourseClassification.INPROGRESS,
    timeout: float = 30.0,
) -> list[Course]:
    payload = [
        {
            "index": 0,
            "methodname": COURSES_METHOD,
            "args": {
                "classification": classification.value,
                "sort": "fullname",
                "offset": 0,
                "limit": 0,
            },
        }
    ]

    try:
        response = session.post(
            MOODLE_AJAX_URL,
            params={"sesskey": sesskey},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CourseError("Could not fetch LearnIT courses from Moodle.") from exc

    return parse_courses_response(response.json())


def parse_courses_response(data: Any) -> list[Course]:
    if not isinstance(data, list) or not data:
        raise CourseError("Unexpected Moodle course response.")

    first = data[0]
    if not isinstance(first, dict):
        raise CourseError("Unexpected Moodle course response.")

    if first.get("error"):
        message = first.get("exception", {}).get("message") if isinstance(first.get("exception"), dict) else None
        raise CourseError(message or "Moodle returned an error while listing courses.")

    course_data = first.get("data", {}).get("courses", [])
    if course_data is None:
        course_data = []
    if not isinstance(course_data, list):
        raise CourseError("Unexpected Moodle course list response.")

    return [_parse_course(course) for course in course_data]


def list_courses(
    *,
    cookie: str | None = None,
    cookie_file: Path | str = "cookie.txt",
    classification: CourseClassification = CourseClassification.INPROGRESS,
    include_non_courses: bool = False,
    timeout: float = 30.0,
) -> list[Course]:
    loaded_cookie = auth.load_cookie(cookie=cookie, cookie_file=cookie_file)
    session = auth.build_session(loaded_cookie)
    auth_result = auth.authenticate(
        cookie=loaded_cookie,
        cookie_file=cookie_file,
        session=session,
        timeout=timeout,
    )
    fetched_courses = fetch_courses(
        session,
        sesskey=auth_result.sesskey,
        classification=classification,
        timeout=timeout,
    )
    return filter_courses(fetched_courses, include_non_courses=include_non_courses)


def filter_courses(courses: list[Course], *, include_non_courses: bool = False) -> list[Course]:
    if include_non_courses:
        return courses
    return [course for course in courses if not is_non_course(course)]


def is_non_course(course: Course) -> bool:
    haystack = f"{course.shortname} {course.fullname}".casefold()
    return any(marker in haystack for marker in NON_COURSE_MARKERS)


def format_courses(courses: list[Course]) -> str:
    if not courses:
        return "No current LearnIT courses found."

    rows = [["ID", "Shortname", "Full name", "Start"]]
    rows.extend(
        [
            [
                str(course.id),
                course.shortname,
                course.fullname,
                format_startdate(course.startdate),
            ]
            for course in courses
        ]
    )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines = [
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()
        for row in rows
    ]
    return "\n".join(lines)


def format_startdate(startdate: int | None) -> str:
    if not startdate:
        return ""
    return datetime.fromtimestamp(startdate).strftime("%Y-%m-%d")


def _parse_course(course: Any) -> Course:
    if not isinstance(course, dict):
        raise CourseError("Unexpected course item in Moodle response.")

    try:
        course_id = int(course["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CourseError("Moodle course response is missing a valid course id.") from exc

    shortname = unescape(str(course.get("shortname") or ""))
    fullname = unescape(str(course.get("fullname") or shortname or course_id))
    startdate_value = course.get("startdate")
    startdate = int(startdate_value) if startdate_value else None

    return Course(
        id=course_id,
        shortname=shortname,
        fullname=fullname,
        startdate=startdate,
    )
