from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from learnit_study.extractors import docx, html, pdf, pptx, text


TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".sql", ".py", ".json", ".xml", ".yaml", ".yml"}
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".html", ".htm", *TEXT_EXTENSIONS}


@dataclass(frozen=True)
class ExtractionResult:
    path: Path
    text: str
    extractor: str


def is_supported(path: Path) -> bool:
    return path.suffix.casefold() in SUPPORTED_EXTENSIONS


def extract_file(path: Path) -> ExtractionResult:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return ExtractionResult(path=path, text=pdf.extract_text(path), extractor="pdf")
    if suffix == ".docx":
        return ExtractionResult(path=path, text=docx.extract_text(path), extractor="docx")
    if suffix == ".pptx":
        return ExtractionResult(path=path, text=pptx.extract_text(path), extractor="pptx")
    if suffix in {".html", ".htm"}:
        return ExtractionResult(path=path, text=html.extract_text(path), extractor="html")
    if suffix in TEXT_EXTENSIONS:
        return ExtractionResult(path=path, text=text.extract_text(path), extractor="text")
    raise ValueError(f"Unsupported file type: {path.suffix or '(no extension)'}")
