from __future__ import annotations

import contextlib
import io
import logging
from pathlib import Path

from pypdf import PdfReader


def extract_text(path: str | Path) -> str:
    pypdf_logger = logging.getLogger("pypdf")
    previous_level = pypdf_logger.level
    pypdf_logger.setLevel(logging.ERROR)
    try:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
    finally:
        pypdf_logger.setLevel(previous_level)
    return "\n\n".join(page.strip() for page in pages if page.strip())
