from __future__ import annotations

from pathlib import Path


def extract_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")
