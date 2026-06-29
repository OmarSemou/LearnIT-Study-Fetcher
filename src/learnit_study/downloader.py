from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from learnit_study import auth, parser


SUPPORTED_FILE_TYPES = {"file", "resource"}
SUPPORTED_TYPES = {*SUPPORTED_FILE_TYPES, "folder", "page", "url"}


class DownloadError(RuntimeError):
    """Raised when course material downloading cannot start."""


class DownloadSession(Protocol):
    headers: requests.structures.CaseInsensitiveDict[str] | dict[str, str]

    def get(self, url: str, *, timeout: float, stream: bool = False) -> requests.Response:
        ...


@dataclass
class DownloadSummary:
    course_id: str
    output_dir: Path
    files_downloaded: int
    files_skipped: int
    links_recorded: int
    unsupported_skipped: int
    failures: int


def download_course(
    course_id: str,
    *,
    out: Path | str = "output",
    delay: float = 0.0,
    cookie: str | None = None,
    cookie_file: Path | str = "cookie.txt",
    session: DownloadSession | None = None,
    course_page: parser.CoursePage | None = None,
    course_name: str | None = None,
    timeout: float = 30.0,
) -> DownloadSummary:
    active_session = session
    if active_session is None:
        loaded_cookie = auth.load_cookie(cookie=cookie, cookie_file=cookie_file)
        active_session = auth.build_session(loaded_cookie)
        if course_page is not None:
            auth.authenticate(
                cookie=loaded_cookie,
                cookie_file=cookie_file,
                session=active_session,
                timeout=timeout,
            )

    parsed_page = course_page
    if parsed_page is None:
        html = parser.fetch_course_page_html(
            course_id,
            cookie=cookie,
            cookie_file=cookie_file,
            session=active_session,
            timeout=timeout,
        )
        parsed_page = parser.parse_course_page(html, course_id=course_id)

    resolved_course_name = course_name or parsed_page.title or f"Course {course_id}"
    root = Path(out) / f"{safe_filename(course_id)} - {safe_filename(resolved_course_name)}"
    root.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "course_id": course_id,
        "course_name": resolved_course_name,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "sections": [],
        "activities_processed": [],
        "files_downloaded": [],
        "links_recorded": [],
        "skipped_unsupported": [],
        "failures": [],
    }

    files_downloaded = 0
    files_skipped = 0
    links_recorded = 0

    for section in parsed_page.sections:
        section_dir = root / safe_filename(section.name)
        materials_dir = section_dir / "materials"
        materials_dir.mkdir(parents=True, exist_ok=True)
        section_links: list[dict[str, str]] = []
        section_manifest: dict[str, Any] = {
            "section_name": section.name,
            "activities_processed": [],
            "files_downloaded": [],
            "links_recorded": [],
            "skipped_unsupported": [],
            "failures": [],
        }

        for activity in section.activities:
            activity_record = activity_to_dict(activity)
            manifest["activities_processed"].append(activity_record)
            section_manifest["activities_processed"].append(activity_record)

            try:
                if activity.type in SUPPORTED_FILE_TYPES:
                    downloaded, skipped = _download_resource_files(
                        active_session,
                        activity=activity,
                        target_dir=materials_dir,
                        timeout=timeout,
                    )
                elif activity.type == "folder":
                    downloaded, skipped = _download_resource_files(
                        active_session,
                        activity=activity,
                        target_dir=materials_dir / safe_filename(activity.name),
                        timeout=timeout,
                    )
                elif activity.type == "page":
                    downloaded, skipped = _save_page_activity(
                        active_session,
                        activity=activity,
                        target_dir=materials_dir,
                        timeout=timeout,
                    )
                elif activity.type == "url":
                    link_record = _resolve_url_activity(
                        active_session,
                        activity=activity,
                        timeout=timeout,
                    )
                    section_links.append(link_record)
                    section_manifest["links_recorded"].append(link_record)
                    manifest["links_recorded"].append(link_record)
                    links_recorded += 1
                    downloaded, skipped = [], []
                else:
                    skipped_record = {
                        **activity_record,
                        "reason": f"Unsupported activity type: {activity.type}",
                    }
                    section_manifest["skipped_unsupported"].append(skipped_record)
                    manifest["skipped_unsupported"].append(skipped_record)
                    downloaded, skipped = [], []

                section_manifest["files_downloaded"].extend(downloaded)
                manifest["files_downloaded"].extend(downloaded)
                files_downloaded += len(downloaded)
                files_skipped += len(skipped)
            except Exception as exc:  # Keep one bad activity from stopping the course.
                failure = {
                    **activity_record,
                    "reason": str(exc),
                }
                section_manifest["failures"].append(failure)
                manifest["failures"].append(failure)

            if delay > 0:
                time.sleep(delay)

        _write_links(section_dir / "links.md", section_links)
        _write_json(section_dir / "section_manifest.json", section_manifest)
        manifest["sections"].append(
            {
                "name": section.name,
                "path": str(section_dir),
                **section_manifest,
            }
        )

    _write_json(root / "manifest.json", manifest)
    return DownloadSummary(
        course_id=course_id,
        output_dir=root,
        files_downloaded=files_downloaded,
        files_skipped=files_skipped,
        links_recorded=links_recorded,
        unsupported_skipped=len(manifest["skipped_unsupported"]),
        failures=len(manifest["failures"]),
    )


def format_summary(summary: DownloadSummary) -> str:
    return "\n".join(
        [
            f"Downloaded LearnIT course {summary.course_id}.",
            f"Output: {summary.output_dir}",
            f"Files downloaded: {summary.files_downloaded}",
            f"Files skipped: {summary.files_skipped}",
            f"Links recorded: {summary.links_recorded}",
            f"Unsupported activities skipped: {summary.unsupported_skipped}",
            f"Failures: {summary.failures}",
        ]
    )


def safe_filename(value: str, *, max_length: int = 120, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length].rstrip(" .") or fallback


def activity_to_dict(activity: parser.Activity) -> dict[str, Any]:
    return {
        "name": activity.name,
        "type": activity.type,
        "cmid": activity.cmid,
        "url": activity.url,
        "section_name": activity.section_name,
    }


def _download_resource_files(
    session: DownloadSession,
    *,
    activity: parser.Activity,
    target_dir: Path,
    timeout: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    response = session.get(activity.url, timeout=timeout)
    response.raise_for_status()
    links = _pluginfile_links(response.text, activity.url)
    downloaded: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for link in links:
        result = _download_file(session, link, target_dir=target_dir, timeout=timeout)
        (skipped if result["status"] == "skipped" else downloaded).append(result)
    return downloaded, skipped


def _save_page_activity(
    session: DownloadSession,
    *,
    activity: parser.Activity,
    target_dir: Path,
    timeout: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    response = session.get(activity.url, timeout=timeout)
    response.raise_for_status()
    target_dir.mkdir(parents=True, exist_ok=True)
    html_path = _unique_path(target_dir / f"{safe_filename(activity.name)}.html")
    html_path.write_text(_main_page_html(response.text), encoding="utf-8")
    downloaded = [
        {
            "url": activity.url,
            "path": str(html_path),
            "status": "downloaded",
        }
    ]
    skipped: list[dict[str, str]] = []
    for link in _pluginfile_links(response.text, activity.url):
        result = _download_file(session, link, target_dir=target_dir, timeout=timeout)
        (skipped if result["status"] == "skipped" else downloaded).append(result)
    return downloaded, skipped


def _resolve_url_activity(
    session: DownloadSession,
    *,
    activity: parser.Activity,
    timeout: float,
) -> dict[str, str]:
    try:
        response = session.get(activity.url, timeout=timeout)
        response.raise_for_status()
        resolved = response.url
        if resolved == activity.url:
            resolved = _external_link(response.text, activity.url) or activity.url
    except requests.RequestException:
        resolved = activity.url
    return {
        "name": activity.name,
        "url": resolved,
        "activity_url": activity.url,
    }


def _download_file(
    session: DownloadSession,
    url: str,
    *,
    target_dir: Path,
    timeout: float,
) -> dict[str, str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    response = session.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    filename = safe_filename(_filename_from_response(url, response.headers.get("content-disposition")))
    target = target_dir / filename
    if target.exists() and target.stat().st_size > 0:
        return {"url": url, "path": str(target), "status": "skipped"}

    part = target.with_name(f"{target.name}.part")
    with part.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 64):
            if chunk:
                handle.write(chunk)
    part.replace(target)
    return {"url": url, "path": str(target), "status": "downloaded"}


def _pluginfile_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = node.get("href", "")
        if "/pluginfile.php/" not in href:
            continue
        url = urljoin(base_url, href)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _main_page_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("#region-main, main, [role='main']")
    return str(main or soup)


def _external_link(html: str, base_url: str) -> str | None:
    base_host = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("a[href]"):
        href = urljoin(base_url, node.get("href", ""))
        if urlparse(href).netloc and urlparse(href).netloc != base_host:
            return href
    return None


def _filename_from_response(url: str, content_disposition: str | None) -> str:
    if content_disposition:
        utf8_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
        plain_match = re.search(r'filename="?([^";]+)"?', content_disposition)
        if utf8_match:
            return unquote(utf8_match.group(1))
        if plain_match:
            return plain_match.group(1)
    path_name = Path(unquote(urlparse(url).path)).name
    return path_name or "download"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise DownloadError(f"Could not create unique path for {path}")


def _write_links(path: Path, links: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"- [{link['name']}]({link['url']})" for link in links]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
