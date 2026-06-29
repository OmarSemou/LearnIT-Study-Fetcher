from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from learnit_study import downloader
from learnit_study.extraction import resolve_course_dir


DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
QUALITY_MODEL = "gemini-3.5-flash"
SUPPORTED_PROVIDERS = {DEFAULT_PROVIDER}
MODEL_PRICING_USD_PER_1M = {
    DEFAULT_MODEL: {"input": 0.25, "output": 1.50},
    QUALITY_MODEL: {"input": 2.70, "output": 16.20},
}
DEFAULT_DETAIL_LEVEL = "exam"
STANDARD_DETAIL_LEVEL = "standard"
SUPPORTED_DETAIL_LEVELS = {STANDARD_DETAIL_LEVEL, DEFAULT_DETAIL_LEVEL}
DETAIL_OUTPUT_TOKEN_RATIOS = {
    STANDARD_DETAIL_LEVEL: 0.25,
    DEFAULT_DETAIL_LEVEL: 0.45,
}
MAX_CHUNK_CHARS = 24_000
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
DEFAULT_REQUESTS_PER_MINUTE = 10
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY = 10.0
AI_NOTES_DIR_NAME = "AI notes"
AI_NOTE_SUFFIX = ".ai-notes.md"
AI_NOTE_STEM_MAX_LENGTH = 80


class AINotesError(RuntimeError):
    """Raised when AI note generation cannot start."""


class AIClient(Protocol):
    def generate(self, *, model: str, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class Material:
    section_dir: Path
    extracted_file: Path
    note_path: Path
    source_material_path: str
    text: str


@dataclass(frozen=True)
class MaterialPlan:
    planned: list[tuple[str, Material]]
    to_generate: list[Material]
    skipped_existing: list[Material]


@dataclass(frozen=True)
class CostEstimate:
    course_dir: Path
    provider: str
    model: str
    detail_level: str
    materials: int
    input_tokens: int
    output_tokens: int
    output_token_ratio: float
    estimated_cost_usd: float


@dataclass(frozen=True)
class AINotesSummary:
    course_dir: Path
    sections_processed: int
    notes_generated: int
    notes_skipped: int
    sections_skipped: int
    failures: int
    estimate: CostEstimate


class RateLimiter:
    def __init__(
        self,
        requests_per_minute: int,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.requests_per_minute = max(1, requests_per_minute)
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            min_interval = 60.0 / self.requests_per_minute
            elapsed = self._monotonic() - self._last_request_at
            wait_for = min_interval - elapsed
            if wait_for > 0:
                self._sleep(wait_for)
        self._last_request_at = self._monotonic()


class GeminiNoteClient:
    def __init__(self, api_key: str) -> None:
        try:
            from google import genai
        except ImportError as exc:
            raise AINotesError(
                "Gemini AI mode requires the google-genai package. "
                'Install dependencies with: python -m pip install -e ".[dev]"'
            ) from exc
        self._client = genai.Client(api_key=api_key)

    def generate(self, *, model: str, prompt: str) -> str:
        response = self._client.models.generate_content(model=model, contents=prompt)
        text = getattr(response, "text", None)
        if text:
            return str(text).strip()
        candidates = getattr(response, "candidates", None)
        if candidates:
            return str(candidates[0]).strip()
        return str(response).strip()


def estimate_cost(
    course_id: str | None = None,
    *,
    course_dir: Path | str | None = None,
    out: Path | str = "output",
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    detail_level: str = DEFAULT_DETAIL_LEVEL,
    max_materials: int | None = None,
    overwrite: bool = False,
) -> CostEstimate:
    provider, model = validate_provider_model(provider, model)
    detail_level = validate_detail_level(detail_level)
    resolved_course_dir = resolve_course_dir(course=course_id, out=out, course_dir=course_dir)
    plan = collect_material_plan(resolved_course_dir, max_materials=max_materials, overwrite=overwrite)
    materials = plan.to_generate
    input_tokens = sum(estimate_tokens(material.text) for material in materials)
    output_token_ratio = DETAIL_OUTPUT_TOKEN_RATIOS[detail_level]
    output_tokens = int(input_tokens * output_token_ratio)
    pricing = MODEL_PRICING_USD_PER_1M[model]
    estimated_cost = (input_tokens / 1_000_000 * pricing["input"]) + (
        output_tokens / 1_000_000 * pricing["output"]
    )
    return CostEstimate(
        course_dir=resolved_course_dir,
        provider=provider,
        model=model,
        detail_level=detail_level,
        materials=len(materials),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        output_token_ratio=output_token_ratio,
        estimated_cost_usd=estimated_cost,
    )


def generate_ai_notes(
    course_id: str | None = None,
    *,
    course_dir: Path | str | None = None,
    out: Path | str = "output",
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    detail_level: str = DEFAULT_DETAIL_LEVEL,
    max_materials: int | None = None,
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    overwrite: bool = False,
    progress: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    client_factory: Any | None = None,
) -> AINotesSummary:
    estimate = estimate_cost(
        course_id,
        course_dir=course_dir,
        out=out,
        provider=provider,
        model=model,
        detail_level=detail_level,
        max_materials=max_materials,
        overwrite=overwrite,
    )
    detail_level = estimate.detail_level
    plan = collect_material_plan(estimate.course_dir, max_materials=max_materials, overwrite=overwrite)
    api_key = os.environ.get(GEMINI_API_KEY_ENV)
    client = None
    if plan.to_generate:
        if not api_key:
            raise AINotesError(
                "GEMINI_API_KEY is not set. Set it in your environment before using --ai Gemini mode."
            )
        client = (client_factory or GeminiNoteClient)(api_key)
    limiter = RateLimiter(requests_per_minute, sleep=sleep, monotonic=monotonic)
    generated_at = datetime.now(timezone.utc).isoformat()
    section_records: dict[Path, list[dict[str, Any]]] = {}
    section_failures: dict[Path, list[dict[str, str]]] = {}
    section_skips: dict[Path, list[dict[str, str]]] = {}
    notes_generated = 0
    notes_skipped = 0
    failures = 0

    total_materials = len(plan.planned)
    for index, (action, material) in enumerate(plan.planned, start=1):
        if action == "skip":
            notes_skipped += 1
            emit_progress(
                progress,
                f"[{index}/{total_materials}] Skipped existing notes for {material.source_material_path}",
            )
            section_skips.setdefault(material.section_dir, []).append(
                {
                    "source_extracted_path": material.extracted_file.relative_to(material.section_dir).as_posix(),
                    "source_material_path": material.source_material_path,
                    "ai_notes_path": material.note_path.relative_to(material.section_dir).as_posix(),
                    "reason": "Existing non-empty notes file",
                }
            )
            continue

        emit_progress(progress, f"[{index}/{total_materials}] Generating notes for {material.source_material_path}")
        try:
            if client is None:
                raise AINotesError("Gemini client was not initialized.")
            note_text = generate_material_note(
                client,
                model=model,
                material=material,
                detail_level=detail_level,
                limiter=limiter,
                retry_attempts=retry_attempts,
                retry_base_delay=retry_base_delay,
                sleep=sleep,
                progress=progress,
            )
            write_ai_note(material.note_path, note_text)
            notes_generated += 1
            emit_progress(progress, f"[{index}/{total_materials}] Generated {material.note_path.name}")
            section_records.setdefault(material.section_dir, []).append(
                {
                    "source_extracted_path": material.extracted_file.relative_to(material.section_dir).as_posix(),
                    "source_material_path": material.source_material_path,
                    "ai_notes_path": material.note_path.relative_to(material.section_dir).as_posix(),
                    "provider": provider,
                    "model": model,
                    "detail_level": detail_level,
                }
            )
        except Exception as exc:
            failures += 1
            error = sanitize_error(str(exc), api_key)
            emit_progress(progress, f"[{index}/{total_materials}] Failed {material.source_material_path}: {error}")
            section_failures.setdefault(material.section_dir, []).append(
                {
                    "source_extracted_path": material.extracted_file.relative_to(material.section_dir).as_posix(),
                    "source_material_path": material.source_material_path,
                    "error": error,
                }
            )

    processed_sections = sorted(
        {material.section_dir for _, material in plan.planned},
        key=lambda path: str(path),
    )
    for section_dir in processed_sections:
        records = section_records.get(section_dir, [])
        failures_for_section = section_failures.get(section_dir, [])
        skips_for_section = section_skips.get(section_dir, [])
        _update_section_manifest(
            section_dir,
            {
                "notes_generated": bool(records) or bool(skips_for_section),
                "notes_path": None,
                "ai_notes_generated": bool(records),
                "ai_note_path": None,
                "per_material_ai_notes_files": records,
                "ai_note_skipped_existing": skips_for_section,
                "ai_note_failures": failures_for_section,
                "notes_generated_at": generated_at,
                "note_generation_mode": "ai",
                "note_generation_provider": provider,
                "note_generation_model": model,
                "note_generation_detail_level": detail_level,
                "note_generation_requests_per_minute": requests_per_minute,
                "note_generation_retry_attempts": retry_attempts,
                "note_generation_retry_base_delay": retry_base_delay,
                "note_generation_estimate": estimate_to_dict(estimate),
                "note_generation_errors": [failure["error"] for failure in failures_for_section],
            },
        )

    all_section_dirs = [path for path in estimate.course_dir.iterdir() if path.is_dir()]
    sections_skipped = max(0, len(all_section_dirs) - len(processed_sections))
    _update_top_manifest(
        estimate.course_dir,
        {
            "sections_processed": len(processed_sections),
            "notes_generated": notes_generated,
            "notes_skipped": notes_skipped,
            "sections_skipped": sections_skipped,
            "failures": failures,
            "notes_generated_at": generated_at,
            "note_generation_mode": "ai",
            "note_generation_provider": provider,
            "note_generation_model": model,
            "note_generation_detail_level": detail_level,
            "note_generation_requests_per_minute": requests_per_minute,
            "note_generation_retry_attempts": retry_attempts,
            "note_generation_retry_base_delay": retry_base_delay,
            "note_generation_estimate": estimate_to_dict(estimate),
        },
    )
    return AINotesSummary(
        course_dir=estimate.course_dir,
        sections_processed=len(processed_sections),
        notes_generated=notes_generated,
        notes_skipped=notes_skipped,
        sections_skipped=sections_skipped,
        failures=failures,
        estimate=estimate,
    )


def collect_materials(
    course_dir: Path,
    *,
    max_materials: int | None = None,
    overwrite: bool = False,
) -> list[Material]:
    return collect_material_plan(course_dir, max_materials=max_materials, overwrite=overwrite).to_generate


def collect_material_plan(
    course_dir: Path,
    *,
    max_materials: int | None = None,
    overwrite: bool = False,
) -> MaterialPlan:
    planned: list[tuple[str, Material]] = []
    to_generate: list[Material] = []
    skipped_existing: list[Material] = []
    for section_dir in sorted((path for path in course_dir.iterdir() if path.is_dir()), key=lambda path: path.name):
        extracted_dir = section_dir / "extracted"
        if not extracted_dir.exists():
            continue
        ai_notes_dir = section_dir / AI_NOTES_DIR_NAME
        used_note_names: set[str] = set()
        for extracted_file in sorted(extracted_dir.glob("*.md"), key=lambda path: path.name):
            text = extracted_file.read_text(encoding="utf-8", errors="replace")
            source_material_path = source_path_from_extracted(text) or extracted_file.name
            material = Material(
                section_dir=section_dir,
                extracted_file=extracted_file,
                note_path=ai_note_path(
                    ai_notes_dir=ai_notes_dir,
                    source_material_path=source_material_path,
                    extracted_file=extracted_file,
                    used_note_names=used_note_names,
                ),
                source_material_path=source_material_path,
                text=text,
            )
            if not overwrite and material.note_path.exists() and material.note_path.stat().st_size > 0:
                skipped_existing.append(material)
                planned.append(("skip", material))
                continue
            if max_materials is not None and len(to_generate) >= max_materials:
                continue
            to_generate.append(material)
            planned.append(("generate", material))
    return MaterialPlan(planned=planned, to_generate=to_generate, skipped_existing=skipped_existing)


def ai_note_path(
    *,
    ai_notes_dir: Path,
    source_material_path: str,
    extracted_file: Path,
    used_note_names: set[str] | None = None,
) -> Path:
    source_stem = Path(source_material_path).stem or extracted_file.stem
    safe_stem = downloader.safe_filename(
        source_stem,
        max_length=AI_NOTE_STEM_MAX_LENGTH,
        fallback="material",
    )
    candidate = fit_ai_note_path(ai_notes_dir / f"{safe_stem}{AI_NOTE_SUFFIX}", source_stem=safe_stem)

    if used_note_names is not None:
        while candidate.name in used_note_names:
            hash_suffix = short_hash(f"{source_material_path}:{extracted_file.as_posix()}")
            stem_with_hash = downloader.safe_filename(
                f"{safe_stem}-{hash_suffix}",
                max_length=AI_NOTE_STEM_MAX_LENGTH,
                fallback="material",
            )
            candidate = fit_ai_note_path(ai_notes_dir / f"{stem_with_hash}{AI_NOTE_SUFFIX}", source_stem=stem_with_hash)
            safe_stem = stem_with_hash
        used_note_names.add(candidate.name)

    return candidate


def fit_ai_note_path(path: Path, *, source_stem: str) -> Path:
    if len(str(path.resolve())) <= downloader.WINDOWS_SAFE_PART_PATH_LENGTH:
        return path

    parent_length = len(str(path.parent.resolve()))
    available_stem_length = downloader.WINDOWS_SAFE_PART_PATH_LENGTH - parent_length - 1 - len(AI_NOTE_SUFFIX)
    if available_stem_length <= 0:
        shortened = short_hash(source_stem)
    else:
        shortened = downloader.safe_filename(
            source_stem,
            max_length=available_stem_length,
            fallback="material",
        )
    return path.with_name(f"{shortened}{AI_NOTE_SUFFIX}")


def short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:6]


def write_ai_note(ai_note_path: Path, note_text: str) -> None:
    ai_note_path.parent.mkdir(parents=True, exist_ok=True)
    ai_note_path.write_text(note_text.rstrip() + "\n", encoding="utf-8")


def generate_material_note(
    client: AIClient,
    *,
    model: str,
    material: Material,
    detail_level: str = DEFAULT_DETAIL_LEVEL,
    limiter: RateLimiter | None = None,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] | None = None,
) -> str:
    detail_level = validate_detail_level(detail_level)
    limiter = limiter or RateLimiter(DEFAULT_REQUESTS_PER_MINUTE, sleep=sleep)
    chunks = chunk_text(material.text)
    if len(chunks) == 1:
        return generate_with_retry(
            client,
            model=model,
            prompt=build_note_prompt(material=material, text=chunks[0], detail_level=detail_level),
            limiter=limiter,
            retry_attempts=retry_attempts,
            retry_base_delay=retry_base_delay,
            sleep=sleep,
            progress=progress,
        )

    partial_notes = [
        generate_with_retry(
            client,
            model=model,
            prompt=build_chunk_prompt(
                material=material,
                text=chunk,
                index=index,
                total=len(chunks),
                detail_level=detail_level,
            ),
            limiter=limiter,
            retry_attempts=retry_attempts,
            retry_base_delay=retry_base_delay,
            sleep=sleep,
            progress=progress,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    return generate_with_retry(
        client,
        model=model,
        prompt=build_merge_prompt(material=material, partial_notes=partial_notes, detail_level=detail_level),
        limiter=limiter,
        retry_attempts=retry_attempts,
        retry_base_delay=retry_base_delay,
        sleep=sleep,
        progress=progress,
    )


def generate_with_retry(
    client: AIClient,
    *,
    model: str,
    prompt: str,
    limiter: RateLimiter,
    retry_attempts: int,
    retry_base_delay: float,
    sleep: Callable[[float], None],
    progress: Callable[[str], None] | None = None,
) -> str:
    attempts = max(1, retry_attempts)
    for attempt in range(1, attempts + 1):
        try:
            limiter.wait()
            return client.generate(model=model, prompt=prompt)
        except Exception as exc:
            if not is_rate_limit_error(exc) or attempt >= attempts:
                raise
            delay = retry_base_delay * (2 ** (attempt - 1))
            emit_progress(
                progress,
                f"Rate limit detected. Retry {attempt + 1}/{attempts} in {delay:g} seconds.",
            )
            sleep(delay)
    raise AINotesError("Gemini request failed unexpectedly.")


def is_rate_limit_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".casefold()
    return any(
        marker in text
        for marker in (
            "429",
            "rate limit",
            "ratelimit",
            "resourceexhausted",
            "resource exhausted",
            "quota",
        )
    )


def emit_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def build_note_prompt(*, material: Material, text: str, detail_level: str = DEFAULT_DETAIL_LEVEL) -> str:
    detail_level = validate_detail_level(detail_level)
    if detail_level == STANDARD_DETAIL_LEVEL:
        return build_standard_note_prompt(material=material, text=text)
    return build_exam_note_prompt(material=material, text=text)


def build_standard_note_prompt(*, material: Material, text: str) -> str:
    return f"""You are creating concise study notes for a student using extracted course material.

Rules:
- Be clear and structured.
- Do not invent facts beyond the provided extracted text.
- Preserve important terminology.
- Include exam-relevant questions.
- If the extracted text is messy due to PDF extraction, still produce useful notes.
- If the content is too sparse, say so.

Output Markdown with these sections:
1. Title
2. Short summary
3. Key concepts
4. Important definitions
5. Important examples/cases
6. Connections to the course/topic
7. Possible exam questions
8. Revision checklist
9. Source material filename

Source material: {material.source_material_path}

Extracted text:
{text}
"""


def build_exam_note_prompt(*, material: Material, text: str) -> str:
    return f"""You are creating detailed exam preparation notes from extracted course material.

Purpose:
- These are standalone study notes, not a short summary.
- A student should be able to study from this without rereading the entire PDF immediately.
- Aim for around 1500-3000 words for normal lecture slides/readings when the source contains enough content.
- For very short or sparse materials, write shorter notes and explicitly say that the source content was limited.

Rules:
- Use only the extracted text below. Do not hallucinate or invent facts.
- Preserve important terminology, distinctions, examples, and course language from the source.
- Prefer deep explanations over generic bullet points.
- Explain why ideas matter for exams, projects, databases, information systems, business processes, SQL, ERD, BPMN, normalization, or project work when the source supports those connections.
- If PDF extraction is messy or unclear, still produce useful structured notes and say what is unclear.
- If examples or cases appear in the material, explain what they demonstrate and why they are exam-relevant.

Output exactly this Markdown structure:

# AI Study Notes: <material title>

## 1. What this material is about
Explain the main topic in clear student-friendly language.

## 2. Why this material matters for the course
Explain how this material connects to the course, lectures, exam, project work, databases, information systems, business processes, or other relevant course themes supported by the source.

## 3. Detailed explanation of the main ideas
This should be the longest section. Explain each major idea in depth.
For each important concept, explain what it means, why it matters, how it works, how it connects to the rest of the material, and include a simple example where possible.

## 4. Key concepts and terminology
Create a Markdown table with columns: Term, Clear definition, Why it matters, Example.

## 5. Important theories, models, frameworks, or classifications
If the material contains theories, models, frameworks, taxonomies, stages, dimensions, categories, or lists, explain them deeply. For each one, name it, explain it, explain each part, and explain how students might use it in an exam answer.

## 6. Important examples and cases
Explain examples/cases from the material in detail. For each example, explain what happened, what concept it demonstrates, why it is exam-relevant, and how it could be used in an answer.

## 7. Connections between concepts
Explain how the ideas connect to each other. Use subsections or bullets. Only use connections supported by the extracted text.

## 8. Exam-focused explanation
Write this as if helping a student prepare for an oral or written exam. Include what the student must be able to explain, distinctions they must know, common mistakes or misunderstandings, useful examples to remember, and what would make an exam answer strong.

## 9. Possible exam questions with model answers
Include 8-15 exam questions when the source has enough substance. For each question, include a detailed model answer that is useful to study from, not just one sentence.

Format:

### Question 1: ...
**Model answer:**
...

## 10. Quick revision checklist
Use specific exam-oriented checkboxes.

## 11. Very short last-minute recap
Give a compressed recap the student can read right before the exam.

## 12. Source material
Include the original source filename/path.

Source material: {material.source_material_path}

Extracted text:
{text}
"""


def build_chunk_prompt(
    *,
    material: Material,
    text: str,
    index: int,
    total: int,
    detail_level: str = DEFAULT_DETAIL_LEVEL,
) -> str:
    detail_level = validate_detail_level(detail_level)
    if detail_level == STANDARD_DETAIL_LEVEL:
        instruction = "Create concise partial study notes for this chunk."
    else:
        instruction = (
            "Create detailed partial exam-preparation notes for this chunk. Preserve important details, "
            "terminology, examples, cases, theories, distinctions, and potential exam angles. "
            "Do not compress this into a short summary."
        )
    return f"""{instruction}

This is chunk {index} of {total}.
Use only this extracted text. Do not invent facts. If the text is messy or sparse, say so.

Source material: {material.source_material_path}

Extracted text chunk:
{text}
"""


def build_merge_prompt(
    *,
    material: Material,
    partial_notes: list[str],
    detail_level: str = DEFAULT_DETAIL_LEVEL,
) -> str:
    detail_level = validate_detail_level(detail_level)
    joined = "\n\n--- PARTIAL NOTES ---\n\n".join(partial_notes)
    if detail_level == STANDARD_DETAIL_LEVEL:
        return f"""Merge these partial notes into one final per-material study note.
Do not add facts that are not present in the partial notes.

Use Markdown sections:
1. Title
2. Short summary
3. Key concepts
4. Important definitions
5. Important examples/cases
6. Connections to the course/topic
7. Possible exam questions
8. Revision checklist
9. Source material filename

Source material: {material.source_material_path}

Partial notes:
{joined}
"""
    return f"""Merge these partial notes into one final detailed per-material exam preparation note.
Do not collapse the material into a short summary. Preserve the important details, terminology, examples, cases, distinctions, theories, frameworks, and exam angles from the partial notes.
Do not add facts that are not present in the partial notes.

The final output must follow this full Markdown structure:

# AI Study Notes: <material title>

## 1. What this material is about
## 2. Why this material matters for the course
## 3. Detailed explanation of the main ideas
## 4. Key concepts and terminology
Use a Markdown table with columns: Term, Clear definition, Why it matters, Example.
## 5. Important theories, models, frameworks, or classifications
## 6. Important examples and cases
## 7. Connections between concepts
## 8. Exam-focused explanation
## 9. Possible exam questions with model answers
Include 8-15 questions with detailed model answers when the partial notes contain enough substance.
## 10. Quick revision checklist
Use specific exam-oriented checkboxes.
## 11. Very short last-minute recap
## 12. Source material

Source material: {material.source_material_path}

Partial notes:
{joined}
"""


def chunk_text(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    clean = text.strip()
    if len(clean) <= max_chars:
        return [clean]
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(start + max_chars, len(clean))
        split_at = clean.rfind("\n\n", start, end)
        if split_at <= start:
            split_at = end
        chunks.append(clean[start:split_at].strip())
        start = split_at
    return [chunk for chunk in chunks if chunk]


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def validate_provider_model(provider: str, model: str) -> tuple[str, str]:
    normalized_provider = provider.casefold()
    if normalized_provider not in SUPPORTED_PROVIDERS:
        raise AINotesError("Only the Gemini AI provider is supported right now. Use --provider gemini.")
    if model not in MODEL_PRICING_USD_PER_1M:
        supported = ", ".join(MODEL_PRICING_USD_PER_1M)
        raise AINotesError(f"Unsupported Gemini model: {model}. Supported models: {supported}.")
    return DEFAULT_PROVIDER, model


def validate_detail_level(detail_level: str) -> str:
    normalized = detail_level.casefold()
    if normalized not in SUPPORTED_DETAIL_LEVELS:
        supported = ", ".join(sorted(SUPPORTED_DETAIL_LEVELS))
        raise AINotesError(f"Unsupported detail level: {detail_level}. Supported levels: {supported}.")
    return normalized


def format_estimate(estimate: CostEstimate) -> str:
    return "\n".join(
        [
            "AI note generation cost estimate (approximate):",
            f"Course folder: {estimate.course_dir}",
            f"Provider: {estimate.provider}",
            f"Model: {estimate.model}",
            f"Detail level: {estimate.detail_level}",
            f"Materials: {estimate.materials}",
            f"Estimated input tokens: {estimate.input_tokens}",
            f"Estimated output tokens: {estimate.output_tokens}",
            f"Output token ratio: {estimate.output_token_ratio:.0%}",
            f"Estimated cost: ${estimate.estimated_cost_usd:.6f}",
        ]
    )


def estimate_to_dict(estimate: CostEstimate) -> dict[str, Any]:
    return {
        "provider": estimate.provider,
        "model": estimate.model,
        "detail_level": estimate.detail_level,
        "materials": estimate.materials,
        "input_tokens": estimate.input_tokens,
        "output_tokens": estimate.output_tokens,
        "output_token_ratio": estimate.output_token_ratio,
        "estimated_cost_usd": estimate.estimated_cost_usd,
    }


def safe_filename(value: str, *, max_length: int = 120, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length].rstrip(" .") or fallback


def source_path_from_extracted(text: str) -> str | None:
    match = re.search(r"^- Original material path:\s+`?([^`\n]+)`?\s*$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def sanitize_error(message: str, api_key: str | None) -> str:
    return message.replace(api_key, "[REDACTED]") if api_key else message


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
