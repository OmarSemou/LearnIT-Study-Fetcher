from __future__ import annotations

from collections import OrderedDict
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
import soupsieve

from learnit_study import auth


COURSE_VIEW_URL = "https://learnit.itu.dk/course/view.php"
SECTION_NODE_SELECTOR = (
    'li.section, li.course-section, [data-region="course-section"], '
    '[data-region="course-subsection"], .subsection, .course-subsection, '
    '.section-card, .card, details'
)
ACTIVITY_NODE_SELECTOR = "li.activity, .activity-item, [data-cmid]"
ACTIVITY_LINK_SELECTOR = 'a[href*="/mod/"][href*="view.php"]'
ACTIVITY_SUFFIXES = (
    "File",
    "Folder",
    "Page",
    "URL",
    "Assignment",
    "Forum",
    "Quiz",
    "Video",
    "Fil",
    "Mappe",
    "Side",
    "Opgave",
)


class ParserError(RuntimeError):
    """Raised when a course page cannot be fetched or parsed."""


class CoursePageSession(Protocol):
    headers: requests.structures.CaseInsensitiveDict[str] | dict[str, str]

    def get(self, url: str, *, timeout: float) -> requests.Response:
        ...


@dataclass(frozen=True)
class Activity:
    name: str
    type: str
    cmid: int
    url: str
    section_name: str


@dataclass(frozen=True)
class CourseSection:
    name: str
    activities: list[Activity]


@dataclass(frozen=True)
class CoursePage:
    course_id: str
    sections: list[CourseSection]


def fetch_course_page_html(
    course_id: str,
    *,
    cookie: str | None = None,
    cookie_file: Path | str = "cookie.txt",
    session: CoursePageSession | None = None,
    timeout: float = 30.0,
) -> str:
    loaded_cookie = auth.load_cookie(cookie=cookie, cookie_file=cookie_file)
    active_session = session or auth.build_session(loaded_cookie)
    auth.authenticate(
        cookie=loaded_cookie,
        cookie_file=cookie_file,
        session=active_session,
        timeout=timeout,
    )

    try:
        response = active_session.get(f"{COURSE_VIEW_URL}?id={course_id}", timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ParserError(f"Could not fetch LearnIT course page for course {course_id}.") from exc

    return response.text


def inspect_course(
    course_id: str,
    *,
    cookie: str | None = None,
    cookie_file: Path | str = "cookie.txt",
    timeout: float = 30.0,
) -> CoursePage:
    html = fetch_course_page_html(
        course_id,
        cookie=cookie,
        cookie_file=cookie_file,
        timeout=timeout,
    )
    return parse_course_page(html, course_id=course_id)


def parse_course_page(
    html: str,
    *,
    course_id: str = "",
    base_url: str = "https://learnit.itu.dk",
) -> CoursePage:
    soup = BeautifulSoup(html, "html.parser")
    seen_cmids: set[int] = set()
    grouped: OrderedDict[str, list[Activity]] = OrderedDict()

    for link in _activity_links(soup):
        url = urljoin(base_url, link.get("href", ""))
        cmid = _activity_cmid(link, url)
        if cmid is None or cmid in seen_cmids:
            continue

        activity_type = _activity_type(url)
        if activity_type == "unknown":
            continue

        container = _activity_container(link)
        section_name = _closest_section_name(link, fallback=f"Section {len(grouped) + 1}")
        activity = Activity(
            name=clean_activity_name(_activity_name(container, link)),
            type=activity_type,
            cmid=cmid,
            url=url,
            section_name=section_name,
        )
        seen_cmids.add(cmid)
        grouped.setdefault(section_name, []).append(activity)

    sections = [
        CourseSection(name=section_name, activities=activities)
        for section_name, activities in grouped.items()
    ]

    return CoursePage(course_id=course_id, sections=sections)


def format_course_page(course_page: CoursePage) -> str:
    visible_sections = [section for section in course_page.sections if section.activities]
    if not visible_sections:
        return "No sections found."

    lines: list[str] = []
    for section in visible_sections:
        lines.append(section.name)
        for activity in section.activities:
            lines.append(f"  - {activity.name} [{activity.type}, cmid={activity.cmid}]")
    return "\n".join(lines)


def clean_activity_name(name: str) -> str:
    cleaned = _normalize_space(name)
    for suffix in ACTIVITY_SUFFIXES:
        pattern = rf"\s+{re.escape(suffix)}$"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or name.strip()


def _activity_links(soup: BeautifulSoup) -> list[Tag]:
    links = [link for link in soup.select(ACTIVITY_LINK_SELECTOR) if isinstance(link, Tag)]
    return [link for link in links if _activity_type(urljoin("https://learnit.itu.dk", link.get("href", ""))) != "unknown"]


def _activity_container(link: Tag) -> Tag:
    for parent in link.parents:
        if isinstance(parent, Tag) and _is_activity_node(parent):
            return parent
    return link


def _closest_section_name(link: Tag, *, fallback: str) -> str:
    activity_container = _activity_container(link)
    for ancestor in link.parents:
        if not isinstance(ancestor, Tag):
            continue
        if _is_activity_node(ancestor) and ancestor is not activity_container:
            continue
        heading = _nearest_meaningful_heading(ancestor, before_node=link, activity_container=activity_container)
        if heading:
            return heading
    return fallback


def _nearest_meaningful_heading(
    ancestor: Tag,
    *,
    before_node: Tag,
    activity_container: Tag,
) -> str | None:
    heading_nodes = [
        node
        for node in ancestor.select(
            "h1, h2, h3, h4, summary, .sectionname, "
            ".course-section-header, .card-header"
        )
        if isinstance(node, Tag)
        and not _is_descendant_of(node, activity_container)
        and _appears_before(node, before_node)
    ]
    for node in reversed(heading_nodes):
        text = _normalize_space(node.get_text(" ", strip=True))
        if _is_meaningful_section_heading(text):
            return text
    return None


def _is_meaningful_section_heading(text: str) -> bool:
    normalized = _normalize_space(text)
    if not normalized:
        return False
    if normalized.casefold() in {"collapse", "expand", "collapse all", "collapse expand"}:
        return False
    if re.fullmatch(r"(file|folder|page|url|assignment|forum|quiz|video)", normalized, re.IGNORECASE):
        return False
    return True


def _appears_before(candidate: Tag, target: Tag) -> bool:
    for element in candidate.next_elements:
        if element is target:
            return True
    return candidate is target


def _find_section_nodes(soup: BeautifulSoup) -> list[Tag]:
    sections = soup.select(SECTION_NODE_SELECTOR)
    if sections:
        candidates = [
            section
            for section in sections
            if isinstance(section, Tag) and _is_section_container(section)
        ]
        top_level = _without_nested_section_nodes(candidates)
        if top_level:
            return top_level

    main = soup.select_one("main, #region-main, [role='main']")
    if isinstance(main, Tag):
        return [main]
    return [soup]


def _parse_section_node(
    section_node: Tag,
    *,
    seen_cmids: set[int],
    base_url: str,
    fallback: str,
) -> list[CourseSection]:
    child_sections = _child_section_nodes(section_node)
    section_name = _section_name(section_node, fallback=fallback)
    parsed_sections = [
        CourseSection(
            name=section_name,
            activities=_section_activities(
                section_node,
                section_name=section_name,
                seen_cmids=seen_cmids,
                base_url=base_url,
                excluded_containers=child_sections,
            ),
        )
    ]

    for index, child_section in enumerate(child_sections, start=1):
        parsed_sections.extend(
            _parse_section_node(
                child_section,
                seen_cmids=seen_cmids,
                base_url=base_url,
                fallback=f"{section_name} {index}",
            )
        )
    return parsed_sections


def _section_name(section_node: Tag, *, fallback: str) -> str:
    selectors = (
        "h3.sectionname",
        ".sectionname",
        ".course-section-header h3",
        ".course-section-header",
        ".card-header",
        "h2",
        "h3",
        "h4",
        "h1",
    )
    for selector in selectors:
        for name_node in section_node.select(selector):
            if not isinstance(name_node, Tag):
                continue
            if not _heading_belongs_to_section(name_node, section_node):
                continue
            name = _normalize_space(name_node.get_text(" ", strip=True))
            if name:
                return name
    return fallback


def _section_activities(
    section_node: Tag,
    *,
    section_name: str,
    seen_cmids: set[int],
    base_url: str,
    excluded_containers: list[Tag] | None = None,
) -> list[Activity]:
    activities: list[Activity] = []
    excluded_containers = excluded_containers or []
    activity_nodes = _find_activity_nodes(section_node)
    for activity_node in activity_nodes:
        if any(_is_descendant_of(activity_node, container) for container in excluded_containers):
            continue

        link = _activity_link(activity_node)
        if not link:
            continue

        url = urljoin(base_url, link.get("href", ""))
        cmid = _activity_cmid(activity_node, url)
        if cmid is None or cmid in seen_cmids:
            continue

        name = clean_activity_name(_activity_name(activity_node, link))
        activity_type = _activity_type(url)
        seen_cmids.add(cmid)
        activities.append(
            Activity(
                name=name,
                type=activity_type,
                cmid=cmid,
                url=url,
                section_name=section_name,
            )
        )
    return activities


def _find_activity_nodes(section_node: Tag) -> list[Tag]:
    nodes = [node for node in section_node.select(ACTIVITY_NODE_SELECTOR) if isinstance(node, Tag)]
    links = [link for link in section_node.select(ACTIVITY_LINK_SELECTOR) if isinstance(link, Tag)]
    activity_nodes = list(nodes)
    for link in links:
        if any(_is_descendant_of(link, node) for node in nodes):
            continue
        activity_nodes.append(link)
    return activity_nodes


def _activity_link(activity_node: Tag) -> Tag | None:
    if activity_node.name == "a" and activity_node.get("href"):
        return activity_node
    link = activity_node.select_one(ACTIVITY_LINK_SELECTOR)
    if isinstance(link, Tag):
        return link
    fallback = activity_node.select_one("a[href]")
    return fallback if isinstance(fallback, Tag) else None


def _activity_name(activity_node: Tag, link: Tag) -> str:
    instance_name = activity_node.select_one(".instancename")
    if instance_name:
        text = instance_name.get_text(" ", strip=True)
        if text:
            return text
    return link.get_text(" ", strip=True)


def _activity_cmid(activity_node: Tag, url: str) -> int | None:
    for attr in ("data-cmid", "data-id"):
        value = activity_node.get(attr)
        if value and str(value).isdigit():
            return int(str(value))

    node_id = activity_node.get("id")
    if node_id:
        match = re.search(r"(\d+)$", str(node_id))
        if match:
            return int(match.group(1))

    query_id = parse_qs(urlparse(url).query).get("id", [""])[0]
    if query_id.isdigit():
        return int(query_id)
    return None


def _activity_type(url: str) -> str:
    path = urlparse(url).path
    match = re.search(r"/mod/([^/]+)/", path)
    if not match:
        return "unknown"

    moodle_type = match.group(1)
    return {
        "resource": "file",
        "folder": "folder",
        "page": "page",
        "url": "url",
        "assign": "assignment",
        "forum": "forum",
        "quiz": "quiz",
        "kalvidres": "video",
        "kalvidassign": "video",
    }.get(moodle_type, moodle_type)


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _child_section_nodes(section_node: Tag) -> list[Tag]:
    candidates = [
        candidate
        for candidate in section_node.select(SECTION_NODE_SELECTOR)
        if isinstance(candidate, Tag)
        and candidate is not section_node
        and _is_section_container(candidate)
    ]
    return _without_nested_section_nodes(candidates)


def _without_nested_section_nodes(candidates: list[Tag]) -> list[Tag]:
    candidate_set = set(candidates)
    filtered: list[Tag] = []
    for candidate in candidates:
        if any(parent in candidate_set for parent in candidate.parents):
            continue
        filtered.append(candidate)
    return filtered


def _is_section_container(node: Tag) -> bool:
    if _is_activity_node(node):
        return False
    if _matches(node, "li.section, li.course-section, [data-region='course-section']"):
        return True
    return _has_section_heading(node) and _has_activity_link(node)


def _is_activity_node(node: Tag) -> bool:
    return _matches(node, ACTIVITY_NODE_SELECTOR)


def _has_section_heading(node: Tag) -> bool:
    return bool(
        node.select_one(
            "h1, h2, h3, h4, h3.sectionname, .sectionname, "
            ".course-section-header, .card-header"
        )
    )


def _has_activity_link(node: Tag) -> bool:
    return bool(node.select_one(ACTIVITY_LINK_SELECTOR))


def _heading_belongs_to_section(heading: Tag, section_node: Tag) -> bool:
    for parent in heading.parents:
        if parent is section_node:
            return True
        if isinstance(parent, Tag) and _is_section_container(parent):
            return False
    return False


def _is_descendant_of(node: Tag, container: Tag) -> bool:
    return any(parent is container for parent in node.parents)


def _matches(node: Tag, selector: str) -> bool:
    return bool(soupsieve.match(selector, node))
