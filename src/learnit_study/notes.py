from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learnit_study.extraction import resolve_course_dir


class NotesError(RuntimeError):
    """Raised when local note generation cannot start."""


@dataclass(frozen=True)
class NotesSummary:
    course_dir: Path
    sections_processed: int
    notes_generated: int
    sections_skipped: int
    failures: int
    notes_skipped: int = 0


STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "because",
    "been",
    "chapter",
    "course",
    "data",
    "from",
    "have",
    "into",
    "lecture",
    "materials",
    "more",
    "section",
    "source",
    "that",
    "the",
    "their",
    "this",
    "through",
    "using",
    "were",
    "with",
}


def generate(
    course_id: str | None = None,
    *,
    course_dir: Path | str | None = None,
    out: Path | str = "output",
    ai: bool = False,
    no_ai: bool = True,
    provider: str = "gemini",
    model: str = "gemini-3.1-flash-lite",
    detail_level: str = "exam",
    max_materials: int | None = None,
    requests_per_minute: int = 10,
    retry_attempts: int = 3,
    retry_base_delay: float = 10.0,
    overwrite: bool = False,
    progress: Any | None = None,
) -> NotesSummary:
    if ai:
        from learnit_study import ai_notes

        try:
            summary = ai_notes.generate_ai_notes(
                course_id,
                course_dir=course_dir,
                out=out,
                provider=provider,
                model=model,
                detail_level=detail_level,
                max_materials=max_materials,
                requests_per_minute=requests_per_minute,
                retry_attempts=retry_attempts,
                retry_base_delay=retry_base_delay,
                overwrite=overwrite,
                progress=progress,
            )
        except ai_notes.AINotesError as exc:
            raise NotesError(str(exc)) from exc
        return NotesSummary(
            course_dir=summary.course_dir,
            sections_processed=summary.sections_processed,
            notes_generated=summary.notes_generated,
            notes_skipped=summary.notes_skipped,
            sections_skipped=summary.sections_skipped,
            failures=summary.failures,
        )
    resolved_course_dir = resolve_course_dir(course=course_id, out=out, course_dir=course_dir)
    return generate_course_notes(resolved_course_dir)


def generate_course_notes(course_dir: Path) -> NotesSummary:
    section_dirs = [path for path in course_dir.iterdir() if path.is_dir()]
    generated_at = datetime.now(timezone.utc).isoformat()
    notes_generated = 0
    sections_skipped = 0
    failures = 0

    for section_dir in section_dirs:
        try:
            result = generate_section_notes(section_dir, generated_at=generated_at)
            if result == "generated":
                notes_generated += 1
            elif result == "skipped":
                sections_skipped += 1
        except Exception as exc:
            failures += 1
            _update_section_manifest(
                section_dir,
                {
                    "notes_generated": False,
                    "notes_path": None,
                    "notes_generated_at": generated_at,
                    "note_generation_mode": "local",
                    "note_generation_errors": [str(exc)],
                },
            )

    _update_top_manifest(
        course_dir,
        {
            "sections_processed": len(section_dirs),
            "notes_generated": notes_generated,
            "sections_skipped": sections_skipped,
            "failures": failures,
            "notes_generated_at": generated_at,
            "note_generation_mode": "local",
        },
    )
    return NotesSummary(
        course_dir=course_dir,
        sections_processed=len(section_dirs),
        notes_generated=notes_generated,
        sections_skipped=sections_skipped,
        failures=failures,
    )


def generate_section_notes(section_dir: Path, *, generated_at: str) -> str:
    extracted_dir = section_dir / "extracted"
    extracted_files = sorted(extracted_dir.glob("*.md")) if extracted_dir.exists() else []
    if not extracted_files:
        _update_section_manifest(
            section_dir,
            {
                "notes_generated": False,
                "notes_path": None,
                "notes_generated_at": generated_at,
                "note_generation_mode": "local",
                "note_generation_warnings": ["Missing extracted/ material files. Run text extraction first."],
                "note_generation_errors": [],
            },
        )
        return "skipped"

    notes_dir = section_dir / "notes"
    notes_dir.mkdir(exist_ok=True)
    old_combined_path = section_dir / "notes.md"
    if old_combined_path.exists():
        old_combined_path.unlink()
    per_material_notes = generate_per_material_notes(section_dir, notes_dir)
    warnings = []
    if any(record.get("empty_text") for record in per_material_notes):
        warnings.append("One or more extracted materials had no text.")
    _update_section_manifest(
        section_dir,
        {
            "notes_generated": True,
            "notes_path": None,
            "per_material_notes_files": per_material_notes,
            "notes_generated_at": generated_at,
            "note_generation_mode": "local",
            "note_generation_warnings": warnings,
            "note_generation_errors": [],
        },
    )
    return "generated"


def generate_per_material_notes(section_dir: Path, notes_dir: Path) -> list[dict[str, Any]]:
    extracted_dir = section_dir / "extracted"
    if not extracted_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for extracted_file in sorted(extracted_dir.glob("*.md")):
        extracted_text = extracted_file.read_text(encoding="utf-8", errors="replace")
        source_path = source_path_from_extracted(extracted_text) or extracted_file.name
        note_path = unique_note_path(notes_dir, extracted_file.stem)
        note_path.write_text(build_notes(extracted_file.stem, extracted_text), encoding="utf-8")
        records.append(
            {
                "source_extracted_path": extracted_file.relative_to(section_dir).as_posix(),
                "source_material_path": source_path,
                "notes_path": note_path.relative_to(section_dir).as_posix(),
                "empty_text": not has_extracted_body_text(extracted_text),
            }
        )
    return records


def build_notes(section_name: str, extracted_text: str) -> str:
    sources = extract_sources(extracted_text)
    body_text = remove_source_heading_lines(extracted_text)
    concepts = extract_concepts(body_text, sources)
    snippets = extract_snippets(body_text)

    if not has_extracted_body_text(extracted_text):
        return "\n".join(
            [
                f"# Study notes - {section_name}",
                "",
                "These notes were generated locally from extracted text and may need manual review.",
                "",
                "No extracted text was available for this material.",
                "",
            ]
        )

    return "\n".join(
        [
            f"# Study notes - {section_name}",
            "",
            "These notes were generated locally from extracted text and may need manual review.",
            "",
            "## Overview",
            "",
            overview_text(section_name, sources, concepts),
            "",
            "## Key source materials",
            "",
            bullet_list(sources, fallback="No source filenames were detected."),
            "",
            "## Key concepts and terms",
            "",
            bullet_list(concepts, fallback="No strong repeated concepts were detected."),
            "",
            "## Important details",
            "",
            bullet_list(snippets, fallback="No concise details were detected."),
            "",
            "## Examples and cases",
            "",
            bullet_list(find_examples(body_text), fallback="No obvious examples or cases were detected."),
            "",
            "## Possible exam questions",
            "",
            bullet_list(possible_questions(section_name, sources, concepts)),
            "",
            "## Revision checklist",
            "",
            checklist_items(sources, concepts),
            "",
            "## Sources used",
            "",
            bullet_list(sources, fallback="No source filenames were detected."),
            "",
        ]
    )


def extract_sources(text: str) -> list[str]:
    sources: list[str] = []
    for match in re.finditer(r"^- Original material path:\s+`?([^`\n]+)`?\s*$", text, flags=re.MULTILINE):
        source = match.group(1).strip()
        if source and source not in sources:
            sources.append(source)
    for match in re.finditer(r"^## Source:\s+(.+)$", text, flags=re.MULTILINE):
        source = match.group(1).strip()
        if source and source not in sources:
            sources.append(source)
    return sources[:20]


def remove_source_heading_lines(text: str) -> str:
    without_source_headings = re.sub(r"^## Source:\s+.+$", "", text, flags=re.MULTILINE)
    return re.sub(r"^- (Source filename|Original material path):\s+.+$", "", without_source_headings, flags=re.MULTILINE)


def extract_concepts(text: str, sources: list[str]) -> list[str]:
    candidates: list[str] = []
    for line in text.splitlines():
        clean = clean_line(line)
        if is_concept_line(clean):
            candidates.append(clean)

    words = [
        word.casefold()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", text)
        if word.casefold() not in STOPWORDS
    ]
    for word, count in Counter(words).most_common(30):
        if count >= 2:
            candidates.append(word.title())

    for source in sources:
        stem = Path(source).stem.replace("_", " ").replace("-", " ")
        if stem:
            candidates.append(stem)
    return unique(candidates, limit=12)


def extract_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    for line in text.splitlines():
        clean = clean_line(line)
        if 60 <= len(clean) <= 240 and not clean.startswith("#"):
            snippets.append(truncate(clean, 220))
    if not snippets:
        sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
        snippets.extend(truncate(sentence, 220) for sentence in sentences if 60 <= len(sentence) <= 260)
    return unique(snippets, limit=8)


def find_examples(text: str) -> list[str]:
    examples = [
        clean_line(line)
        for line in text.splitlines()
        if re.search(r"\b(example|case|exercise|scenario)\b", line, flags=re.IGNORECASE)
    ]
    return unique([truncate(example, 180) for example in examples if example], limit=6)


def possible_questions(section_name: str, sources: list[str], concepts: list[str]) -> list[str]:
    questions = [f"What are the main learning goals of {section_name}?"]
    for concept in concepts[:5]:
        questions.append(f"How would you explain {concept} in your own words?")
    for source in sources[:3]:
        questions.append(f"What are the most important points from {Path(source).name}?")
    return unique(questions, limit=8)


def checklist_items(sources: list[str], concepts: list[str]) -> str:
    items = []
    for concept in concepts[:6]:
        items.append(f"- [ ] Review {concept}.")
    for source in sources[:4]:
        items.append(f"- [ ] Revisit {Path(source).name}.")
    if not items:
        items.append("- [ ] Manually review the extracted text for this section.")
    return "\n".join(items)


def overview_text(section_name: str, sources: list[str], concepts: list[str]) -> str:
    source_count = len(sources)
    concept_text = ", ".join(concepts[:3]) if concepts else "no strong repeated concepts"
    return (
        f"This local draft covers {section_name}. It is based on {source_count} detected source "
        f"material(s) and highlights {concept_text}."
    )


def bullet_list(items: list[str], *, fallback: str | None = None) -> str:
    if not items:
        return f"- {fallback or 'None detected.'}"
    return "\n".join(f"- {item}" for item in items)


def clean_line(line: str) -> str:
    clean = re.sub(r"^[-*#>\s]+", "", line).strip()
    return re.sub(r"\s+", " ", clean)


def is_concept_line(line: str) -> bool:
    if not line or len(line) > 90:
        return False
    if line.startswith("---") or line.startswith(("Source:", "Source filename:", "Original material path:")):
        return False
    if line == "_No extractable text found._":
        return False
    if re.match(r"^(slide \d+|extracted text)", line, flags=re.IGNORECASE):
        return False
    return bool(re.search(r"[A-Za-z]", line))


def truncate(value: str, max_length: int) -> str:
    clean = clean_line(value)
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 3].rstrip() + "..."


def unique(items: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = clean_line(item)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def source_path_from_extracted(text: str) -> str | None:
    match = re.search(r"^- Original material path:\s+`?([^`\n]+)`?\s*$", text, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    sources = extract_sources(text)
    return sources[0] if sources else None


def has_extracted_body_text(text: str) -> bool:
    body_lines = [
        line
        for line in text.splitlines()
        if line.strip()
        and not line.startswith("#")
        and not line.startswith("- Source filename:")
        and not line.startswith("- Original material path:")
        and line.strip() != "_No extractable text found._"
    ]
    return bool(body_lines)


def unique_note_path(notes_dir: Path, stem: str) -> Path:
    safe_stem = safe_filename(stem)
    candidate = notes_dir / f"{safe_stem}.notes.md"
    if not candidate.exists():
        return candidate
    for index in range(2, 10_000):
        numbered = notes_dir / f"{safe_stem} ({index}).notes.md"
        if not numbered.exists():
            return numbered
    raise NotesError(f"Could not create unique note file for {stem}")


def safe_filename(value: str, *, max_length: int = 120, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length].rstrip(" .") or fallback


def format_summary(summary: NotesSummary) -> str:
    return "\n".join(
        [
            f"Generated local study notes for {summary.course_dir}.",
            f"Sections processed: {summary.sections_processed}",
            f"Notes generated: {summary.notes_generated}",
            f"Notes skipped: {summary.notes_skipped}",
            f"Sections skipped: {summary.sections_skipped}",
            f"Failures: {summary.failures}",
        ]
    )


def _update_section_manifest(section_dir: Path, update: dict[str, Any]) -> None:
    path = section_dir / "section_manifest.json"
    manifest = _read_json(path)
    manifest.pop("combined_notes_path", None)
    manifest.update(update)
    _write_json(path, manifest)


def _update_top_manifest(course_dir: Path, summary: dict[str, Any]) -> None:
    path = course_dir / "manifest.json"
    manifest = _read_json(path)
    manifest["note_generation_summary"] = summary
    _write_json(path, manifest)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
