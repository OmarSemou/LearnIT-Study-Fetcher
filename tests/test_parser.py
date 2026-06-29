from __future__ import annotations

from pathlib import Path

from learnit_study import parser


FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_section_parsing() -> None:
    page = parser.parse_course_page(read_fixture("course_page.html"), course_id="3025489")

    assert page.course_id == "3025489"
    assert [section.name for section in page.sections] == [
        "Week 1 - Intro",
        "Week 2 - Architecture",
    ]


def test_activity_parsing() -> None:
    page = parser.parse_course_page(read_fixture("course_page.html"))
    first_activity = page.sections[0].activities[0]

    assert first_activity.name == "Lecture slides"
    assert first_activity.type == "file"
    assert first_activity.cmid == 101
    assert first_activity.url == "https://learnit.itu.dk/mod/resource/view.php?id=101"
    assert first_activity.section_name == "Week 1 - Intro"


def test_duplicate_cmids_are_skipped() -> None:
    page = parser.parse_course_page(read_fixture("course_page.html"))
    cmids = [
        activity.cmid
        for section in page.sections
        for activity in section.activities
    ]

    assert cmids == [101, 102, 201, 202]


def test_activity_names_are_cleaned() -> None:
    page = parser.parse_course_page(read_fixture("course_page.html"))
    names = [
        activity.name
        for section in page.sections
        for activity in section.activities
    ]

    assert "Lecture slides" in names
    assert "Reading guide" in names
    assert "Exercise files" in names
    assert "Practice quiz" in names


def test_fallback_behavior_if_no_section_nodes_are_found() -> None:
    page = parser.parse_course_page(read_fixture("course_page_no_sections.html"))

    assert len(page.sections) == 1
    assert page.sections[0].name == "Course front page"
    assert page.sections[0].activities[0].name == "External reading"
    assert page.sections[0].activities[0].type == "url"
    assert page.sections[0].activities[0].cmid == 301


def test_nested_lecture_activities_are_assigned_to_child_lecture() -> None:
    page = parser.parse_course_page(read_fixture("course_page_nested.html"))
    by_name = {section.name: section for section in page.sections}

    lecture_2 = by_name["Lecture 2: Information Systems in Global Business Today"]
    assert [activity.name for activity in lecture_2.activities] == [
        "Laudon chapter PDF",
        "Case Study Jurong",
        "Information Systems in Global Business Today",
        "Virtual Tour through Microsoft's Datacenter",
        "Exercise 2",
        "Jurong Case Answers",
    ]
    assert all(
        activity.section_name == "Lecture 2: Information Systems in Global Business Today"
        for activity in lecture_2.activities
    )


def test_parent_direct_activities_remain_under_parent() -> None:
    page = parser.parse_course_page(read_fixture("course_page_nested.html"))
    by_name = {section.name: section for section in page.sections}
    parent = by_name["1.Fundamentals of Information Systems"]

    assert [activity.name for activity in parent.activities] == ["Course overview"]


def test_nested_duplicate_cmids_are_still_deduplicated() -> None:
    page = parser.parse_course_page(read_fixture("course_page_nested.html"))
    cmids = [
        activity.cmid
        for section in page.sections
        for activity in section.activities
    ]

    assert cmids.count(21) == 1


def test_empty_sections_are_not_printed_by_default() -> None:
    page = parser.parse_course_page(read_fixture("course_page_nested.html"))
    output = parser.format_course_page(page)

    assert "Lecture 4: Empty lecture" not in output


def test_nested_cli_style_output_does_not_show_stolen_child_activities_under_parent() -> None:
    page = parser.parse_course_page(read_fixture("course_page_nested.html"))
    output = parser.format_course_page(page)

    assert "Lecture 2: Information Systems in Global Business Today" in output
    assert "Laudon chapter PDF" in output

    parent_block = output.split("Lecture 2: Information Systems in Global Business Today")[0]
    assert "1.Fundamentals of Information Systems" in parent_block
    assert "Course overview" in parent_block
    assert "Laudon chapter PDF" not in parent_block


def test_real_like_nested_cards_use_closest_lecture_heading() -> None:
    page = parser.parse_course_page(read_fixture("course_page_database_nested.html"))
    by_name = {section.name: section for section in page.sections}

    lecture_8 = by_name["Lecture 8: The Relational Model and Normalization"]
    lecture_9 = by_name["Lecture 9: Database Design Using Normalization"]

    assert [activity.name for activity in lecture_8.activities] == [
        "Chapter 3 PDF",
        "Exercise 8",
    ]
    assert [activity.name for activity in lecture_9.activities] == [
        "Chapter 4 PDF",
        "Exercise 9",
    ]
    assert all(
        activity.section_name == "Lecture 8: The Relational Model and Normalization"
        for activity in lecture_8.activities
    )


def test_real_like_nested_cards_keep_parent_direct_activity() -> None:
    page = parser.parse_course_page(read_fixture("course_page_database_nested.html"))
    by_name = {section.name: section for section in page.sections}

    assert [activity.name for activity in by_name["3. Database Design"].activities] == [
        "Database overview"
    ]


def test_real_like_nested_cards_ignore_ui_links_and_preserve_order() -> None:
    page = parser.parse_course_page(read_fixture("course_page_database_nested.html"))
    names = [
        activity.name
        for section in page.sections
        for activity in section.activities
    ]

    assert names == [
        "Database overview",
        "Chapter 3 PDF",
        "Exercise 8",
        "Chapter 4 PDF",
        "Exercise 9",
    ]
    assert "Collapse Expand" not in names


def test_real_like_nested_cards_do_not_use_generic_fallback_names() -> None:
    page = parser.parse_course_page(read_fixture("course_page_database_nested.html"))
    output = parser.format_course_page(page)

    assert "Section 5 2" not in output
    assert "Collapse Expand" not in output


def test_real_like_nested_cards_deduplicate_cmid() -> None:
    page = parser.parse_course_page(read_fixture("course_page_database_nested.html"))
    cmids = [
        activity.cmid
        for section in page.sections
        for activity in section.activities
    ]

    assert cmids.count(81) == 1
