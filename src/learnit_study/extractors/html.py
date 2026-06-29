from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup


def extract_text(path: str | Path) -> str:
    soup = BeautifulSoup(Path(path).read_text(encoding="utf-8", errors="replace"), "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    main = soup.select_one("main, #region-main, [role='main']") or soup.body or soup
    return main.get_text("\n", strip=True)
