from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from learnit_study import ai_notes
from learnit_study.cli import app


runner = CliRunner()


def local_tmp_path() -> Path:
    path = Path(".test_tmp") / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def make_course(root: Path, *, course_id: str = "3025533", section_name: str = "Lecture 2") -> Path:
    course_dir = root / f"{course_id} - Demo Course"
    section_dir = course_dir / section_name
    (section_dir / "extracted").mkdir(parents=True)
    (course_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (section_dir / "section_manifest.json").write_text("{}", encoding="utf-8")
    return course_dir


def section_dir(course_dir: Path, section_name: str = "Lecture 2") -> Path:
    return course_dir / section_name


def write_extracted(
    course_dir: Path,
    name: str,
    body: str = "Database systems support business processes.",
    *,
    source_path: str | None = None,
    section_name: str = "Lecture 2",
) -> Path:
    path = section_dir(course_dir, section_name) / "extracted" / f"{name}.md"
    source = source_path or f"materials/{name}.pdf"
    path.write_text(
        f"# Extracted text - {name}.pdf\n\n"
        f"- Source filename: `{name}.pdf`\n"
        f"- Original material path: `{source}`\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def read_section_manifest(course_dir: Path) -> dict:
    return json.loads((section_dir(course_dir) / "section_manifest.json").read_text(encoding="utf-8"))


class FakeGeminiClient:
    calls: list[tuple[str, str]] = []
    responses: list[str] = []
    exceptions: list[Exception] = []
    fail_first: bool = False

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def generate(self, *, model: str, prompt: str) -> str:
        type(self).calls.append((model, prompt))
        if type(self).fail_first:
            type(self).fail_first = False
            raise RuntimeError(f"provider failed with {self.api_key}")
        if type(self).exceptions:
            raise type(self).exceptions.pop(0)
        if "Merge these partial notes" in prompt:
            return "# Final merged notes"
        if type(self).responses:
            return type(self).responses.pop(0)
        return "# AI Notes\n\n## Short summary\n\nMocked Gemini notes.\n"


def reset_fake_client() -> None:
    FakeGeminiClient.calls = []
    FakeGeminiClient.responses = []
    FakeGeminiClient.exceptions = []
    FakeGeminiClient.fail_first = False


def test_ai_gemini_writes_per_material_notes(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--provider",
            "gemini",
            "--model",
            "gemini-3.1-flash-lite",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    note_path = section_dir(course_dir) / "AI notes" / "Lecture 2.ai-notes.md"
    manifest = read_section_manifest(course_dir)
    assert result.exit_code == 0
    assert note_path.exists()
    assert "Mocked Gemini notes" in note_path.read_text(encoding="utf-8")
    assert manifest["note_generation_mode"] == "ai"
    assert manifest["note_generation_provider"] == "gemini"
    assert manifest["note_generation_model"] == "gemini-3.1-flash-lite"
    assert manifest["per_material_ai_notes_files"][0]["ai_notes_path"] == "AI notes/Lecture 2.ai-notes.md"
    assert not (section_dir(course_dir) / "notes" / "Lecture 2.notes.md").exists()


def test_max_materials_limits_ai_generation(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    write_extracted(course_dir, "Reading Chapter 2")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--max-materials",
            "1",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    notes_dir = section_dir(course_dir) / "AI notes"
    assert result.exit_code == 0
    assert len(FakeGeminiClient.calls) == 1
    assert (notes_dir / "Lecture 2.ai-notes.md").exists()
    assert not (notes_dir / "Reading Chapter 2.ai-notes.md").exists()


def test_estimate_cost_command_does_not_need_api_key(monkeypatch) -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2", "a" * 400)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "notes",
            "estimate-cost",
            "--course-dir",
            str(course_dir),
            "--provider",
            "gemini",
            "--model",
            "gemini-3.5-flash",
        ],
    )

    assert result.exit_code == 0
    assert "AI note generation cost estimate" in result.output
    assert "gemini-3.5-flash" in result.output
    assert "Detail level: exam" in result.output
    assert "Output token ratio: 45%" in result.output
    assert "Estimated input tokens" in result.output
    assert "Estimated cost" in result.output


def test_exam_detail_level_uses_detailed_prompt(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(
        course_dir,
        "Lecture 2",
        "Information systems connect technology, organization, and management.",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--detail-level",
            "exam",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    prompt = FakeGeminiClient.calls[0][1]
    manifest = read_section_manifest(course_dir)
    assert result.exit_code == 0
    assert "# AI Study Notes: <material title>" in prompt
    assert "## 3. Detailed explanation of the main ideas" in prompt
    assert "## 9. Possible exam questions with model answers" in prompt
    assert "1500-3000 words" in prompt
    assert manifest["note_generation_detail_level"] == "exam"


def test_standard_detail_level_remains_available(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--detail-level",
            "standard",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    prompt = FakeGeminiClient.calls[0][1]
    assert result.exit_code == 0
    assert "concise study notes" in prompt
    assert "Short summary" in prompt
    assert "# AI Study Notes: <material title>" not in prompt


def test_exam_cost_estimate_uses_higher_output_ratio() -> None:
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2", "a" * 400)

    standard = ai_notes.estimate_cost(course_dir=course_dir, detail_level="standard")
    exam = ai_notes.estimate_cost(course_dir=course_dir, detail_level="exam")

    assert standard.output_token_ratio == 0.25
    assert exam.output_token_ratio == 0.45
    assert exam.output_tokens > standard.output_tokens


def test_confirmation_no_prevents_api_calls(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(app, ["notes", "generate", "--course-dir", str(course_dir), "--ai"], input="n\n")

    assert result.exit_code == 0
    assert "Continue?" in result.output
    assert "Aborted. No API calls were made." in result.output
    assert FakeGeminiClient.calls == []


def test_yes_skips_confirmation(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "Continue?" not in result.output
    assert len(FakeGeminiClient.calls) == 1


def test_api_failure_is_recorded_without_leaking_key(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    write_extracted(course_dir, "Reading Chapter 2")
    FakeGeminiClient.fail_first = True
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    manifest_text = (section_dir(course_dir) / "section_manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert result.exit_code == 0
    assert "super-secret-key" not in result.output
    assert "super-secret-key" not in manifest_text
    assert manifest["ai_note_failures"][0]["error"] == "provider failed with [REDACTED]"
    assert (section_dir(course_dir) / "AI notes" / "Reading Chapter 2.ai-notes.md").exists()


def test_long_material_is_chunked_and_merged(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Long Material", "database\n\n" * 3_000)
    FakeGeminiClient.responses = ["partial one", "partial two"]
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    note_path = section_dir(course_dir) / "AI notes" / "Long Material.ai-notes.md"
    assert result.exit_code == 0
    assert len(FakeGeminiClient.calls) >= 3
    assert "Final merged notes" in note_path.read_text(encoding="utf-8")


def test_rate_limiter_throttles_without_real_sleep() -> None:
    now = {"value": 0.0}
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["value"] += seconds

    limiter = ai_notes.RateLimiter(10, sleep=fake_sleep, monotonic=lambda: now["value"])

    limiter.wait()
    limiter.wait()

    assert sleeps == [6.0]


def test_rate_limit_retry_succeeds(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    FakeGeminiClient.exceptions = [RuntimeError("429 ResourceExhausted quota exceeded")]
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)
    sleeps: list[float] = []

    summary = ai_notes.generate_ai_notes(
        course_dir=course_dir,
        requests_per_minute=1_000_000,
        retry_attempts=3,
        retry_base_delay=2.0,
        sleep=sleeps.append,
    )

    assert summary.notes_generated == 1
    assert summary.failures == 0
    assert len(FakeGeminiClient.calls) == 2
    assert 2.0 in sleeps
    assert (section_dir(course_dir) / "AI notes" / "Lecture 2.ai-notes.md").exists()


def test_retry_failure_is_recorded(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    FakeGeminiClient.exceptions = [
        RuntimeError("429 ResourceExhausted quota exceeded"),
        RuntimeError("429 ResourceExhausted quota exceeded"),
    ]
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    summary = ai_notes.generate_ai_notes(
        course_dir=course_dir,
        requests_per_minute=1_000_000,
        retry_attempts=2,
        retry_base_delay=1.0,
        sleep=lambda seconds: None,
    )

    manifest = read_section_manifest(course_dir)
    assert summary.notes_generated == 0
    assert summary.failures == 1
    assert "ResourceExhausted" in manifest["ai_note_failures"][0]["error"]


def test_existing_ai_notes_are_skipped_by_default(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    notes_dir = section_dir(course_dir) / "AI notes"
    notes_dir.mkdir()
    (notes_dir / "Lecture 2.ai-notes.md").write_text("existing notes", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(app, ["notes", "generate", "--course-dir", str(course_dir), "--ai", "--yes"])

    manifest = read_section_manifest(course_dir)
    assert result.exit_code == 0
    assert "Notes skipped: 1" in result.output
    assert FakeGeminiClient.calls == []
    assert manifest["ai_note_skipped_existing"][0]["ai_notes_path"] == "AI notes/Lecture 2.ai-notes.md"


def test_overwrite_regenerates_existing_notes(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    notes_dir = section_dir(course_dir) / "AI notes"
    notes_dir.mkdir()
    (notes_dir / "Lecture 2.ai-notes.md").write_text("existing notes", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
            "--overwrite",
        ],
    )

    assert result.exit_code == 0
    assert len(FakeGeminiClient.calls) == 1
    assert "Mocked Gemini notes" in (notes_dir / "Lecture 2.ai-notes.md").read_text(encoding="utf-8")


def test_max_materials_counts_new_notes_not_skipped_existing(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    write_extracted(course_dir, "Reading Chapter 2")
    notes_dir = section_dir(course_dir) / "AI notes"
    notes_dir.mkdir()
    (notes_dir / "Lecture 2.ai-notes.md").write_text("existing notes", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--max-materials",
            "1",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(FakeGeminiClient.calls) == 1
    assert "Notes generated: 1" in result.output
    assert "Notes skipped: 1" in result.output
    assert "Mocked Gemini notes" in (notes_dir / "Reading Chapter 2.ai-notes.md").read_text(encoding="utf-8")


def test_existing_local_notes_do_not_cause_ai_skip(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    local_notes_dir = section_dir(course_dir) / "notes"
    local_notes_dir.mkdir()
    (local_notes_dir / "Lecture 2.notes.md").write_text("local notes", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert len(FakeGeminiClient.calls) == 1
    assert (section_dir(course_dir) / "AI notes" / "Lecture 2.ai-notes.md").exists()
    assert (local_notes_dir / "Lecture 2.notes.md").read_text(encoding="utf-8") == "local notes"


def test_nested_folder_material_writes_short_ai_note_path(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    section_name = "Lecture 12 SQL for Database Construction and Application Processing"
    course_dir = make_course(root, section_name=section_name)
    write_extracted(
        course_dir,
        "Readings Chapter 7 (Part 1 &-f3b7bb - Chapter-3195aa",
        source_path="materials/Readings Chapter 7 (Part 1 &-f3b7bb/Chapter-3195aa.pdf",
        section_name=section_name,
    )
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    ai_path = section_dir(course_dir, section_name) / "AI notes" / "Chapter-3195aa.ai-notes.md"
    manifest = json.loads((section_dir(course_dir, section_name) / "section_manifest.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert ai_path.exists()
    assert "FileNotFoundError" not in result.output
    assert manifest["per_material_ai_notes_files"][0]["source_material_path"] == (
        "materials/Readings Chapter 7 (Part 1 &-f3b7bb/Chapter-3195aa.pdf"
    )
    assert manifest["per_material_ai_notes_files"][0]["source_extracted_path"] == (
        "extracted/Readings Chapter 7 (Part 1 &-f3b7bb - Chapter-3195aa.md"
    )
    assert manifest["per_material_ai_notes_files"][0]["ai_notes_path"] == "AI notes/Chapter-3195aa.ai-notes.md"


def test_long_nested_material_path_produces_windows_safe_ai_filename(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    section_name = "Lecture 12 SQL for Database Construction and Application Processing"
    course_dir = make_course(root, section_name=section_name)
    long_source = (
        "materials/Very Long Folder Name With Many Details And Parentheses (Spring 2026)/"
        "Extremely Long Chapter Name About Database Construction Application Processing "
        "And Query Optimization With Extra Words.pdf"
    )
    write_extracted(
        course_dir,
        "Very Long Extracted Source",
        source_path=long_source,
        section_name=section_name,
    )
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    generated = list((section_dir(course_dir, section_name) / "AI notes").glob("*.ai-notes.md"))
    assert result.exit_code == 0
    assert len(generated) == 1
    assert generated[0].name.endswith(".ai-notes.md")
    assert "Very Long Folder" not in generated[0].name
    assert len(str(generated[0].resolve())) <= ai_notes.downloader.WINDOWS_SAFE_PART_PATH_LENGTH


def test_ai_note_parent_is_created_immediately_before_write(monkeypatch) -> None:
    reset_fake_client()
    root = local_tmp_path()
    course_dir = make_course(root)
    write_extracted(course_dir, "Lecture 2")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(ai_notes, "GeminiNoteClient", FakeGeminiClient)
    original_write_text = Path.write_text
    checked = {"value": False}

    def write_text_with_parent_assertion(self: Path, *args, **kwargs):
        if self.name.endswith(".ai-notes.md"):
            checked["value"] = True
            assert self.parent.exists()
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text_with_parent_assertion)

    result = runner.invoke(
        app,
        [
            "notes",
            "generate",
            "--course-dir",
            str(course_dir),
            "--ai",
            "--requests-per-minute",
            "1000000",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert checked["value"] is True
