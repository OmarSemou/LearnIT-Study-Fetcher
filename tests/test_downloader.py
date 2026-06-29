from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
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
        on_iter: Callable[[], None] | None = None,
        iter_error: Exception | None = None,
    ) -> None:
        self.text = text
        self.content = content
        self.url = url
        self.headers = headers or {}
        self.status_code = status_code
        self.on_iter = on_iter
        self.iter_error = iter_error

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size: int):
        if self.on_iter is not None:
            self.on_iter()
        if self.iter_error is not None:
            raise self.iter_error
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
    section_name: str = "Lecture 1",
) -> parser.CoursePage:
    return parser.CoursePage(
        course_id="3025533",
        sections=[parser.CourseSection(name=section_name, activities=activities)],
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


def test_folder_download_creates_nested_parent_before_part_write() -> None:
    root = local_tmp_path()
    folder_url = "https://learnit.itu.dk/mod/folder/view.php?id=246594"
    plugin_url = "https://learnit.itu.dk/pluginfile.php/246594/Chapter%207%20Part%201.pdf"
    expected_folder = (
        root
        / "3025533 - Course 3025533"
        / "Lecture 1"
        / "materials"
        / "Readings Chapter 7 (Part 1 & Part 2)"
    )

    def assert_parent_exists() -> None:
        assert expected_folder.exists()

    session = FakeSession(
        {
            folder_url: FakeResponse(text=f'<a href="{plugin_url}">Download</a>'),
            plugin_url: FakeResponse(
                content=b"chapter",
                headers={"content-disposition": 'filename="Chapter 7 Part 1.pdf"'},
                on_iter=assert_parent_exists,
            ),
        }
    )

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page(
            [
                activity(
                    name="Readings: Chapter 7 (Part 1 & Part 2)",
                    type="folder",
                    cmid=246594,
                    url=folder_url,
                )
            ]
        ),
    )

    assert summary.files_downloaded == 1
    assert (expected_folder / "Chapter 7 Part 1.pdf").read_bytes() == b"chapter"


def test_part_parent_is_created_immediately_before_open(monkeypatch: pytest.MonkeyPatch) -> None:
    root = local_tmp_path()
    target_dir = root / "missing" / "nested" / "materials"
    plugin_url = "https://learnit.itu.dk/pluginfile.php/246594/Chapter%207%20Part%201.pdf"
    session = FakeSession(
        {
            plugin_url: FakeResponse(
                content=b"chapter",
                headers={"content-disposition": 'filename="Chapter 7 Part 1.pdf"'},
            ),
        }
    )
    original_open = Path.open
    checked_part_open = {"value": False}

    def open_with_parent_assertion(self: Path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name == "Chapter 7 Part 1.pdf.part" and "w" in mode:
            checked_part_open["value"] = True
            assert self.parent.exists()
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_parent_assertion)

    result = downloader._download_file(session, plugin_url, target_dir=target_dir, timeout=30.0)

    assert checked_part_open["value"] is True
    assert result["status"] == "downloaded"
    assert (target_dir / "Chapter 7 Part 1.pdf").exists()


def test_long_windows_folder_download_path_is_shortened_and_downloads() -> None:
    root = local_tmp_path()
    course_title = (
        "Database and Information Systems Foundations (Spring 2026) "
        "with a very long extra title for path length testing"
    )
    section_name = (
        "Lecture 12: SQL for Database Construction and Application Processing "
        "with additional path length words"
    )
    folder_name = (
        "Readings: Chapter 7 (Part 1 & Part 2) "
        "Database Construction and Application Processing Pack"
    )
    filename = (
        "Chapter 7 Part 1 Database Construction and Application Processing "
        "Very Long Reading File Name.pdf"
    )
    folder_url = "https://learnit.itu.dk/mod/folder/view.php?id=246594"
    plugin_url = "https://learnit.itu.dk/pluginfile.php/246594/chapter7part1.pdf"
    session = FakeSession(
        {
            folder_url: FakeResponse(text=f'<a href="{plugin_url}">Download</a>'),
            plugin_url: FakeResponse(content=b"chapter", headers={"content-disposition": f'filename="{filename}"'}),
        }
    )

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page(
            [activity(name=folder_name, type="folder", cmid=246594, url=folder_url, section_name=section_name)],
            title=course_title,
            section_name=section_name,
        ),
    )

    data = json.loads((summary.output_dir / "manifest.json").read_text(encoding="utf-8"))
    saved = Path(data["files_downloaded"][0]["path"])
    part_path = saved.with_name(f"{saved.name}.part")
    title_component = summary.output_dir.name.split(" - ", 1)[1]
    assert summary.failures == 0
    assert saved.exists()
    assert saved.suffix == ".pdf"
    assert len(title_component) <= downloader.COURSE_TITLE_MAX_LENGTH
    assert len(saved.parent.parent.name) <= downloader.SECTION_FOLDER_MAX_LENGTH
    assert len(saved.parent.name) <= downloader.FOLDER_ACTIVITY_FOLDER_MAX_LENGTH
    assert len(saved.stem) <= downloader.MATERIAL_FILENAME_STEM_MAX_LENGTH
    assert len(str(part_path.resolve())) <= downloader.WINDOWS_SAFE_PART_PATH_LENGTH
    assert data["activities_processed"][0]["name"] == folder_name
    assert data["files_downloaded"][0]["path"] == str(saved)
    assert data["files_downloaded"][0]["original_filename"] == filename
    assert data["files_downloaded"][0]["saved_filename"] == saved.name


def test_long_similar_material_names_do_not_collide() -> None:
    root = local_tmp_path()
    activity_url = "https://learnit.itu.dk/mod/resource/view.php?id=888"
    plugin_url_1 = "https://learnit.itu.dk/pluginfile.php/888/one.pdf"
    plugin_url_2 = "https://learnit.itu.dk/pluginfile.php/888/two.pdf"
    shared_prefix = "Database Construction and Application Processing Chapter Seven Long Reading Name " * 2
    filename_1 = f"{shared_prefix}alpha.pdf"
    filename_2 = f"{shared_prefix}beta.pdf"
    session = FakeSession(
        {
            activity_url: FakeResponse(text=f'<a href="{plugin_url_1}">One</a><a href="{plugin_url_2}">Two</a>'),
            plugin_url_1: FakeResponse(content=b"one", headers={"content-disposition": f'filename="{filename_1}"'}),
            plugin_url_2: FakeResponse(content=b"two", headers={"content-disposition": f'filename="{filename_2}"'}),
        }
    )

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page([activity(cmid=888, url=activity_url)]),
    )

    data = manifest(root)
    saved_paths = [Path(record["path"]) for record in data["files_downloaded"]]
    saved_names = [path.name for path in saved_paths]
    assert summary.files_downloaded == 2
    assert len(set(saved_names)) == 2
    assert all(path.exists() for path in saved_paths)
    assert all(path.suffix == ".pdf" for path in saved_paths)


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


def test_part_file_is_removed_when_download_stream_fails() -> None:
    root = local_tmp_path()
    folder_url = "https://learnit.itu.dk/mod/folder/view.php?id=246594"
    plugin_url = "https://learnit.itu.dk/pluginfile.php/246594/Chapter%207%20Part%201.pdf"
    expected_folder = (
        root
        / "3025533 - Course 3025533"
        / "Lecture 1"
        / "materials"
        / "Readings Chapter 7 (Part 1 & Part 2)"
    )
    session = FakeSession(
        {
            folder_url: FakeResponse(text=f'<a href="{plugin_url}">Download</a>'),
            plugin_url: FakeResponse(
                headers={"content-disposition": 'filename="Chapter 7 Part 1.pdf"'},
                iter_error=OSError("stream broke"),
            ),
        }
    )

    summary = downloader.download_course(
        "3025533",
        out=root,
        session=session,
        course_page=course_page(
            [
                activity(
                    name="Readings: Chapter 7 (Part 1 & Part 2)",
                    type="folder",
                    cmid=246594,
                    url=folder_url,
                )
            ]
        ),
    )

    data = manifest(root)
    assert summary.failures == 1
    assert "stream broke" in data["failures"][0]["reason"]
    assert not (expected_folder / "Chapter 7 Part 1.pdf.part").exists()
    assert not (expected_folder / "Chapter 7 Part 1.pdf").exists()


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
