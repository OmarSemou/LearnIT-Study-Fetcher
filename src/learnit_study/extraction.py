from __future__ import annotations

import json
import contextlib
import io
import re
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
    per_material_extracted_files: list[dict[str, str]] = []
    extracted_dir = section_dir / "extracted"
    extracted_dir.mkdir(exist_ok=True)
    old_combined_path = section_dir / "extracted_text.md"
    if old_combined_path.exists():
        old_combined_path.unlink()

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
        per_material_path = unique_material_path(extracted_dir, path.relative_to(materials_dir))
        per_material_path.write_text(
            build_per_material_markdown(
                source_name=path.name,
                source_path=relative,
                text=text,
            ),
            encoding="utf-8",
        )
        per_material_record = {
            "path": relative,
            "extractor": result.extractor,
            "extracted_path": per_material_path.relative_to(section_dir).as_posix(),
        }
        extracted_files.append({"path": relative, "extractor": result.extractor})
        per_material_extracted_files.append(per_material_record)
        if not text:
            empty_text.append({"path": relative, "reason": "No extractable text found"})

    manifest.pop("combined_extracted_text_path", None)
    manifest.update(
        {
            "extracted_files": extracted_files,
            "per_material_extracted_files": per_material_extracted_files,
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


def build_per_material_markdown(*, source_name: str, source_path: str, text: str) -> str:
    body = text.strip() or "_No extractable text found._"
    return "\n".join(
        [
            f"# Extracted text - {source_name}",
            "",
            f"- Source filename: `{source_name}`",
            f"- Original material path: `{source_path}`",
            "",
            body,
            "",
        ]
    )


def unique_material_path(extracted_dir: Path, material_relative_path: Path) -> Path:
    safe_stem = safe_filename(" - ".join(material_relative_path.with_suffix("").parts))
    candidate = extracted_dir / f"{safe_stem}.md"
    if not candidate.exists():
        return candidate
    for index in range(2, 10_000):
        numbered = extracted_dir / f"{safe_stem} ({index}).md"
        if not numbered.exists():
            return numbered
    raise ExtractionError(f"Could not create unique extracted file for {material_relative_path}")


def safe_filename(value: str, *, max_length: int = 120, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length].rstrip(" .") or fallback


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
