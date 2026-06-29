from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import requests

from learnit_study import downloader, parser


def local_tmp_path() -> Path:
    path = Path(".test_tmp") / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class FakeResponse:
    def __init__(
        self,
        *,
        text: str = "",
        content: bytes = b"",
        url: str = "https://learnit.itu.dk/test",
        headers: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> None:
        self.text = text
        self.content = content
        self.url = url
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size: int):
        yield self.content


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.requested_urls: list[str] = []

    def get(self, url: str, *, timeout: float, stream: bool = False) -> FakeResponse:
        self.requested_urls.append(url)
        try:
            return self.responses[url]
        except KeyError as exc:
            raise AssertionError(f"Unexpected URL requested: {url}") from exc


def activity(
    *,
    name: str = "Lecture slides",
    type: str = "file",
    cmid: int = 101,
    url: str = "https://learnit.itu.dk/mod/resource/view.php?id=101",
    section_name: str = "Lecture 1",
) -> parser.Activity:
    return parser.Activity(
        name=name,
        type=type,
        cmid=cmid,
        url=url,
        section_name=section_name,
    )


def course_page(
    activities: list[parser.Activity],
    *,
    title: str | None = None,
) -> parser.CoursePage:
    return parser.CoursePage(
        course_id="3025533",
        sections=[parser.CourseSection(name="Lecture 1", activities=activities)],
        title=title,
    )


def manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "3025533 - Course 3025533" / "manifest.json").read_text(encoding="utf-8"))


def test_safe_filename_behavior() -> None:
    assert downloader.safe_filename(' bad<name>:"/\\|?*. ') == "bad name"
    assert downloader.safe_filename("\x00") == "untitled"
    assert not downloader.safe_filename("x" * 200).endswith(" ")


def test_file_activity_download_from_pluginfile_link() -> None:
    root = local_tmp_path()
    plugin_url = "https://learnit.itu.dk/pluginfile.php/1/file.pdf"
    session = FakeSession(
        {
            "https://learnit.itu.dk/mod/resource/view.php?id=101": FakeResponse(
                text=f'<a href="{plugin_url}">Download</a>'
            ),
            plugin_url: FakeResponse(content=b"pdf", headers={"content-disposition": 'filename="file.pdf"'}),
        }
    )

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity()]),
    )

    assert summary.files_downloaded == 1
    assert (root / "3025533 - Course 3025533" / "Lecture 1" / "materials" / "file.pdf").read_bytes() == b"pdf"


def test_output_folder_uses_course_page_title() -> None:
    root = local_tmp_path()

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=FakeSession({}),
        course_page=course_page(
            [activity(name="Quiz", type="quiz", cmid=501)],
            title="Database and Information Systems Foundations (Spring 2026)",
        ),
    )

    expected = root / "3025533 - Database and Information Systems Foundations (Spring 2026)"
    assert summary.output_dir == expected
    assert (expected / "manifest.json").exists()


def test_output_folder_falls_back_when_course_page_has_no_title() -> None:
    root = local_tmp_path()

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=FakeSession({}),
        course_page=course_page([activity(name="Quiz", type="quiz", cmid=501)]),
    )

    assert summary.output_dir == root / "3025533 - Course 3025533"


def test_resource_activity_download_from_pluginfile_link() -> None:
    root = local_tmp_path()
    activity_url = "https://learnit.itu.dk/mod/resource/view.php?id=102"
    plugin_url = "https://learnit.itu.dk/pluginfile.php/2/resource.docx"
    session = FakeSession(
        {
            activity_url: FakeResponse(text=f'<a href="{plugin_url}">Download</a>'),
            plugin_url: FakeResponse(content=b"docx"),
        }
    )

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity(type="resource", cmid=102, url=activity_url)]),
    )

    assert summary.files_downloaded == 1
    assert (root / "3025533 - Course 3025533" / "Lecture 1" / "materials" / "resource.docx").exists()


def test_folder_download_structure() -> None:
    root = local_tmp_path()
    folder_url = "https://learnit.itu.dk/mod/folder/view.php?id=201"
    plugin_url = "https://learnit.itu.dk/pluginfile.php/3/exercise.zip"
    session = FakeSession(
        {
            folder_url: FakeResponse(text=f'<a href="{plugin_url}">Download</a>'),
            plugin_url: FakeResponse(content=b"zip"),
        }
    )

    downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity(name="Exercise 2", type="folder", cmid=201, url=folder_url)]),
    )

    assert (
        root
        / "3025533 - Course 3025533"
        / "Lecture 1"
        / "materials"
        / "Exercise 2"
        / "exercise.zip"
    ).exists()


def test_page_html_saving() -> None:
    root = local_tmp_path()
    page_url = "https://learnit.itu.dk/mod/page/view.php?id=301"
    session = FakeSession({page_url: FakeResponse(text="<main><h1>Reading</h1></main>")})

    downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity(name="Reading guide", type="page", cmid=301, url=page_url)]),
    )

    html = root / "3025533 - Course 3025533" / "Lecture 1" / "materials" / "Reading guide.html"
    assert "Reading" in html.read_text(encoding="utf-8")


def test_url_recording_to_links_md() -> None:
    root = local_tmp_path()
    url_activity = "https://learnit.itu.dk/mod/url/view.php?id=401"
    external = "https://example.com/article"
    session = FakeSession({url_activity: FakeResponse(text="", url=external)})

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity(name="External article", type="url", cmid=401, url=url_activity)]),
    )

    links = root / "3025533 - Course 3025533" / "Lecture 1" / "links.md"
    assert summary.links_recorded == 1
    assert external in links.read_text(encoding="utf-8")


def test_unsupported_activity_is_recorded_as_skipped() -> None:
    root = local_tmp_path()
    summary = downloader.download_course(
        "3025533",
        out=root,
        session=FakeSession({}),
        course_page=course_page([activity(name="Quiz", type="quiz", cmid=501)]),
    )

    data = manifest(root)
    assert summary.unsupported_skipped == 1
    assert data["skipped_unsupported"][0]["name"] == "Quiz"


def test_existing_files_are_skipped() -> None:
    root = local_tmp_path()
    target = root / "3025533 - Course 3025533" / "Lecture 1" / "materials"
    target.mkdir(parents=True)
    (target / "file.pdf").write_bytes(b"existing")
    plugin_url = "https://learnit.itu.dk/pluginfile.php/1/file.pdf"
    session = FakeSession(
        {
            "https://learnit.itu.dk/mod/resource/view.php?id=101": FakeResponse(
                text=f'<a href="{plugin_url}">Download</a>'
            ),
            plugin_url: FakeResponse(content=b"new", headers={"content-disposition": 'filename="file.pdf"'}),
        }
    )

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity()]),
    )

    assert summary.files_downloaded == 0
    assert summary.files_skipped == 1
    assert (target / "file.pdf").read_bytes() == b"existing"


def test_manifest_creation() -> None:
    root = local_tmp_path()
    downloader.download_course(
        "3025533",
        out=root,
        session=FakeSession({}),
        course_page=course_page([activity(name="Quiz", type="quiz", cmid=501)]),
    )

    course_root = root / "3025533 - Course 3025533"
    assert (course_root / "manifest.json").exists()
    assert (course_root / "Lecture 1" / "section_manifest.json").exists()


def test_downloader_uses_activity_url_when_available() -> None:
    root = local_tmp_path()
    activity_url = "https://learnit.itu.dk/mod/resource/view.php?id=777"
    plugin_url = "https://learnit.itu.dk/pluginfile.php/777/custom.pdf"
    session = FakeSession(
        {
            activity_url: FakeResponse(text=f'<a href="{plugin_url}">Download</a>'),
            plugin_url: FakeResponse(content=b"custom"),
        }
    )

    downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity(cmid=777, url=activity_url)]),
    )

    assert session.requested_urls[0] == activity_url
