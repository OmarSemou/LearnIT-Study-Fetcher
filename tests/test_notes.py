from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from learnit_study import notes
from learnit_study.cli import app


runner = CliRunner()


def local_tmp_path() -> Path:
    path = Path(".test_tmp") / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def make_course(root: Path, *, course_id: str = "3025533") -> Path:
    course_dir = root / f"{course_id} - Demo Course"
    section_dir = course_dir / "Lecture 2 Information Systems"
    section_dir.mkdir(parents=True)
    (course_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (section_dir / "section_manifest.json").write_text("{}", encoding="utf-8")
    return course_dir


def write_extracted(section_dir: Path, body: str | None = None) -> None:
    extracted_dir = section_dir / "extracted"
    extracted_dir.mkdir(exist_ok=True)
    if body is not None:
        (extracted_dir / "Lecture 2.md").write_text(body.strip() + "\n", encoding="utf-8")
        return

    lecture = """
# Extracted text - Lecture 2.pdf

- Source filename: `Lecture 2.pdf`
- Original material path: `materials/Lecture 2.pdf`

Information Systems
Business Processes
Information systems support business processes and decision making across organizations.
Case Study Jurong shows how information systems change operational coordination.
"""

    reading = """
# Extracted text - Reading Chapter 2.pdf

- Source filename: `Reading Chapter 2.pdf`
- Original material path: `materials/Reading Chapter 2.pdf`

Information systems connect people, processes, data, and technology.
Exercise 2 asks students to compare business process examples.
"""
    (extracted_dir / "Lecture 2.md").write_text(lecture.strip() + "\n", encoding="utf-8")
    (extracted_dir / "Reading Chapter 2.md").write_text(reading.strip() + "\n", encoding="utf-8")


def section_dir(course_dir: Path) -> Path:
    return course_dir / "Lecture 2 Information Systems"


def read_section_manifest(course_dir: Path) -> dict:
    return json.loads((section_dir(course_dir) / "section_manifest.json").read_text(encoding="utf-8"))


def test_per_material_notes_are_created_from_extracted_files() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    summary = notes.generate(course_id="3025533", out=root)

    notes_path = section_dir(course_dir) / "notes" / "Lecture 2.notes.md"
    assert summary.notes_generated == 1
    assert notes_path.exists()
    assert "# Study notes - Lecture 2" in notes_path.read_text(encoding="utf-8")


def test_combined_notes_md_is_not_created() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    notes.generate(course_dir=course_dir)

    assert not (section_dir(course_dir) / "notes.md").exists()


def test_source_filenames_are_detected_and_listed() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    notes.generate(course_dir=course_dir)

    text = (section_dir(course_dir) / "notes" / "Lecture 2.notes.md").read_text(encoding="utf-8")
    assert "materials/Lecture 2.pdf" in text


def test_key_concepts_section_is_generated() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    notes.generate(course_dir=course_dir)

    text = (section_dir(course_dir) / "notes" / "Lecture 2.notes.md").read_text(encoding="utf-8")
    assert "## Key concepts and terms" in text
    assert "Information Systems" in text


def test_possible_exam_questions_are_generated() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    notes.generate(course_dir=course_dir)

    text = (section_dir(course_dir) / "notes" / "Lecture 2.notes.md").read_text(encoding="utf-8")
    assert "## Possible exam questions" in text
    assert "How would you explain" in text


def test_revision_checklist_is_generated() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    notes.generate(course_dir=course_dir)

    text = (section_dir(course_dir) / "notes" / "Lecture 2.notes.md").read_text(encoding="utf-8")
    assert "## Revision checklist" in text
    assert "- [ ]" in text


def test_very_long_extracted_text_is_truncated_safely() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    long_line = " ".join(["database"] * 1000)
    write_extracted(
        section_dir(course_dir),
        f"# Extracted text - long.txt\n\n- Original material path: `materials/long.txt`\n\n{long_line}",
    )

    notes.generate(course_dir=course_dir)

    notes_text = (section_dir(course_dir) / "notes" / "Lecture 2.notes.md").read_text(encoding="utf-8")
    assert len(notes_text) < 4000
    assert len(notes_text) < len(long_line)


def test_missing_extracted_text_is_skipped_without_crashing() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)

    summary = notes.generate(course_dir=course_dir)

    manifest = read_section_manifest(course_dir)
    assert summary.sections_skipped == 1
    assert manifest["notes_generated"] is False
    assert "Missing extracted/" in manifest["note_generation_warnings"][0]


def test_empty_extracted_text_creates_minimal_notes() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    extracted_dir = section_dir(course_dir) / "extracted"
    extracted_dir.mkdir()
    (extracted_dir / "empty.md").write_text(
        "# Extracted text - empty.txt\n\n- Original material path: `materials/empty.txt`\n\n_No extractable text found._\n",
        encoding="utf-8",
    )

    summary = notes.generate(course_dir=course_dir)

    notes_text = (section_dir(course_dir) / "notes" / "empty.notes.md").read_text(encoding="utf-8")
    manifest = read_section_manifest(course_dir)
    assert summary.notes_generated == 1
    assert "No extracted text was available" in notes_text
    assert manifest["notes_generated"] is True
    assert "One or more extracted materials had no text." in manifest["note_generation_warnings"][0]


def test_section_manifest_is_updated() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    notes.generate(course_dir=course_dir)

    manifest = read_section_manifest(course_dir)
    assert manifest["notes_generated"] is True
    assert manifest["notes_path"] is None
    assert "combined_notes_path" not in manifest
    assert manifest["per_material_notes_files"][0]["notes_path"] == "notes/Lecture 2.notes.md"
    assert manifest["note_generation_mode"] == "local"
    assert manifest["notes_generated_at"]


def test_top_level_manifest_is_updated() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    notes.generate(course_dir=course_dir)

    manifest = json.loads((course_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = manifest["note_generation_summary"]
    assert summary["notes_generated"] == 1
    assert summary["note_generation_mode"] == "local"
    assert summary["notes_generated_at"]


def test_cli_can_find_course_folder_by_course_id_prefix() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    result = runner.invoke(app, ["notes", "generate", "--course", "3025533", "--out", str(root), "--no-ai"])

    assert result.exit_code == 0
    assert "Notes generated: 1" in result.output
    assert (section_dir(course_dir) / "notes" / "Lecture 2.notes.md").exists()


def test_cli_supports_course_dir() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))

    result = runner.invoke(app, ["notes", "generate", "--course-dir", str(course_dir), "--no-ai"])

    assert result.exit_code == 0
    assert "Sections processed: 1" in result.output


def test_ai_flag_without_key_gives_clear_message(monkeypatch) -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(section_dir(course_dir))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = runner.invoke(app, ["notes", "generate", "--course-dir", str(course_dir), "--ai", "--yes"])

    assert result.exit_code == 1
    assert "GEMINI_API_KEY is not set" in result.output
