from __future__ import annotations

from typing import Any

import pytest
import requests

from learnit_study import courses


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.requested_url: str | None = None
        self.requested_params: dict[str, str] | None = None
        self.requested_json: list[dict[str, Any]] | None = None

    def post(
        self,
        url: str,
        *,
        params: dict[str, str],
        json: list[dict[str, Any]],
        timeout: float,
    ) -> FakeResponse:
        self.requested_url = url
        self.requested_params = params
        self.requested_json = json
        return FakeResponse(self.payload)


def test_successful_course_parsing() -> None:
    payload = [
        {
            "error": False,
            "data": {
                "courses": [
                    {
                        "id": 3022795,
                        "shortname": "BDSA &amp; Test",
                        "fullname": "Analysis &amp; Design",
                        "startdate": 1735689600,
                    }
                ]
            },
        }
    ]

    parsed = courses.parse_courses_response(payload)

    assert parsed == [
        courses.Course(
            id=3022795,
            shortname="BDSA & Test",
            fullname="Analysis & Design",
            startdate=1735689600,
        )
    ]


def test_fetch_courses_defaults_to_inprogress_classification() -> None:
    session = FakeSession([{"error": False, "data": {"courses": []}}])

    result = courses.fetch_courses(session, sesskey="abc123")

    assert result == []
    assert session.requested_url == courses.MOODLE_AJAX_URL
    assert session.requested_params == {"sesskey": "abc123"}
    assert session.requested_json is not None
    assert session.requested_json[0]["methodname"] == courses.COURSES_METHOD
    assert session.requested_json[0]["args"]["classification"] == "inprogress"
    assert session.requested_json[0]["args"]["sort"] == "fullname"
    assert session.requested_json[0]["args"]["offset"] == 0
    assert session.requested_json[0]["args"]["limit"] == 0


def test_fetch_courses_can_use_all_classification() -> None:
    session = FakeSession([{"error": False, "data": {"courses": []}}])

    courses.fetch_courses(
        session,
        sesskey="abc123",
        classification=courses.CourseClassification.ALL,
    )

    assert session.requested_json is not None
    assert session.requested_json[0]["args"]["classification"] == "all"


def test_moodle_ajax_error_handling() -> None:
    payload = [
        {
            "error": True,
            "exception": {
                "message": "Invalid sesskey",
            },
        }
    ]

    with pytest.raises(courses.CourseError, match="Invalid sesskey"):
        courses.parse_courses_response(payload)


def test_empty_course_list() -> None:
    payload = [{"error": False, "data": {"courses": []}}]

    assert courses.parse_courses_response(payload) == []
    assert courses.format_courses([]) == "No current LearnIT courses found."


def test_studylab_entries_are_excluded_by_default() -> None:
    normal_course = courses.Course(id=1, shortname="BDSA", fullname="Software Architecture")
    studylab_course = courses.Course(id=2, shortname="GBI-StudyLab-F26", fullname="GBI StudyLab")

    assert courses.filter_courses([normal_course, studylab_course]) == [normal_course]


def test_normal_courses_remain_visible() -> None:
    normal_course = courses.Course(id=1, shortname="BDSA", fullname="Software Architecture")

    assert courses.filter_courses([normal_course]) == [normal_course]


def test_include_non_courses_keeps_studylab_entries() -> None:
    studylab_course = courses.Course(id=2, shortname="GBI-StudyLab-F26", fullname="GBI StudyLab")

    assert courses.filter_courses([studylab_course], include_non_courses=True) == [studylab_course]


def test_non_course_filter_is_case_insensitive() -> None:
    studylab_course = courses.Course(id=2, shortname="gbi", fullname="GBI STUDY LAB Spring 2026")

    assert courses.filter_courses([studylab_course]) == []
