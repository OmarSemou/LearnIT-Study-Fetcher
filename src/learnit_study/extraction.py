from __future__ import annotations

import json
import contextlib
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learnit_study import extractors


class ExtractionError(RuntimeError):
    """Raised when local extraction cannot start."""


@dataclass(frozen=True)
class ExtractionSummary:
    course_dir: Path
    sections_processed: int
    files_extracted: int
    files_skipped: int
    files_failed: int


def extract_course_text(
    *,
    course: str | None = None,
    out: Path | str = "output",
    course_dir: Path | str | None = None,
) -> ExtractionSummary:
    resolved_course_dir = resolve_course_dir(course=course, out=out, course_dir=course_dir)
    section_dirs = [
        path
        for path in resolved_course_dir.iterdir()
        if path.is_dir() and (path / "materials").is_dir()
    ]

    extracted_at = datetime.now(timezone.utc).isoformat()
    files_extracted = 0
    files_skipped = 0
    files_failed = 0

    for section_dir in section_dirs:
        result = extract_section_text(section_dir, extracted_at=extracted_at)
        files_extracted += result["files_extracted"]
        files_skipped += result["files_skipped"]
        files_failed += result["files_failed"]

    _update_top_manifest(
        resolved_course_dir,
        {
            "sections_processed": len(section_dirs),
            "files_extracted": files_extracted,
            "files_skipped": files_skipped,
            "files_failed": files_failed,
            "extracted_at": extracted_at,
        },
    )
    return ExtractionSummary(
        course_dir=resolved_course_dir,
        sections_processed=len(section_dirs),
        files_extracted=files_extracted,
        files_skipped=files_skipped,
        files_failed=files_failed,
    )


def resolve_course_dir(
    *,
    course: str | None = None,
    out: Path | str = "output",
    course_dir: Path | str | None = None,
) -> Path:
    if course_dir is not None:
        path = Path(course_dir)
        if not path.exists():
            raise ExtractionError(f"Course folder does not exist: {path}")
        return path
    if not course:
        raise ExtractionError("Provide --course or --course-dir.")

    output_root = Path(out)
    matches = sorted(path for path in output_root.glob(f"{course} - *") if path.is_dir())
    if not matches:
        raise ExtractionError(
            f"No downloaded course folder found for {course}. Run 'learnit-study course download --course {course}' first."
        )
    if len(matches) > 1:
        raise ExtractionError(f"Multiple course folders found for {course}. Use --course-dir.")
    return matches[0]


def extract_section_text(section_dir: Path, *, extracted_at: str) -> dict[str, int]:
    materials_dir = section_dir / "materials"
    section_name = section_dir.name
    manifest_path = section_dir / "section_manifest.json"
    manifest = _read_json(manifest_path)

    extracted_files: list[dict[str, str]] = []
    skipped_unsupported: list[dict[str, str]] = []
    empty_text: list[dict[str, str]] = []
    extraction_failures: list[dict[str, str]] = []
    markdown_parts = [f"# Extracted text - {section_name}", ""]

    for path in sorted(file for file in materials_dir.rglob("*") if file.is_file()):
        relative = path.relative_to(section_dir).as_posix()
        if not extractors.is_supported(path):
            skipped_unsupported.append({"path": relative, "reason": "Unsupported file type"})
            continue
        try:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                result = extractors.extract_file(path)
        except Exception as exc:
            extraction_failures.append({"path": relative, "error": str(exc)})
            continue

        text = result.text.strip()
        extracted_files.append({"path": relative, "extractor": result.extractor})
        markdown_parts.append(f"## Source: {relative}")
        markdown_parts.append("")
        if text:
            markdown_parts.append(text)
        else:
            markdown_parts.append("_No extractable text found._")
            empty_text.append({"path": relative, "reason": "No extractable text found"})
        markdown_parts.append("")
        markdown_parts.append("---")
        markdown_parts.append("")

    (section_dir / "extracted_text.md").write_text("\n".join(markdown_parts).rstrip() + "\n", encoding="utf-8")

    manifest.update(
        {
            "extracted_files": extracted_files,
            "skipped_unsupported_files": skipped_unsupported,
            "empty_text": empty_text,
            "extraction_failures": extraction_failures,
            "extracted_at": extracted_at,
        }
    )
    _write_json(manifest_path, manifest)
    return {
        "files_extracted": len(extracted_files),
        "files_skipped": len(skipped_unsupported),
        "files_failed": len(extraction_failures),
    }


def format_summary(summary: ExtractionSummary) -> str:
    return "\n".join(
        [
            f"Extracted text from {summary.course_dir}.",
            f"Sections processed: {summary.sections_processed}",
            f"Files extracted: {summary.files_extracted}",
            f"Files skipped: {summary.files_skipped}",
            f"Failures: {summary.files_failed}",
        ]
    )


def _update_top_manifest(course_dir: Path, extraction_summary: dict[str, Any]) -> None:
    manifest_path = course_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["extraction_summary"] = extraction_summary
    _write_json(manifest_path, manifest)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
