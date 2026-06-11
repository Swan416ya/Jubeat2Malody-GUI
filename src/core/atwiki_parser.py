"""解析 atwiki sonicy_memo Ordered by Version 页面文本。"""

from __future__ import annotations

import re
from pathlib import Path

ATWIKI_ORDERED_PAGE = "https://w.atwiki.jp/sonicy_memo/pages/4.html"

VERSION_HEADER_TO_FOLDER: dict[str, str] = {
    "jubeat beyond the Ave.": "jubeat-beyond-ave",
    "jubeat Ave.": "jubeat-ave",
    "jubeat festo": "jubeat-festo",
    "jubeat CLan": "jubeat-clan",
    "jubeat Qubell": "jubeat-qubell",
    "jubeat prop": "jubeat-prop",
    "jubeat saucer fulfill": "jubeat-saucer-fulfill",
    "jubeat saucer": "jubeat-saucer",
    "jubeat copious APPEND": "jubeat-copula",
    "jubeat copious": "jubeat-copula",
    "jubeat knit APPEND": "jubeat-knit",
    "jubeat knit": "jubeat-knit",
    "jubeat ripples APPEND": "jubeat-ripples-append",
    "jubeat ripples": "jubeat-ripples",
    "jubeat 初代": "jubeat",
}

_CHART2_TITLE_RE = re.compile(r"\[\s*2\s*\]\s*$")
_VERSION_HEADER_RE = re.compile(r"^\|\s*jubeat\s+.+\s*\|$")


def is_chart2_title(title: str) -> bool:
    return bool(_CHART2_TITLE_RE.search((title or "").strip()))


def extract_chart2_title_from_row(line: str) -> str | None:
    if "[ 2 ]" not in line and "[2]" not in line:
        return None
    for part in line.split("|"):
        part = part.strip()
        if _CHART2_TITLE_RE.search(part):
            return part
    return None


def parse_version_header(line: str) -> str | None:
    m = _VERSION_HEADER_RE.match(line.strip())
    if not m:
        return None
    inner = m.group(0).strip("| ").strip()
    return VERSION_HEADER_TO_FOLDER.get(inner)


def parse_chart2_debut_entries(text: str) -> list[dict]:
    """返回 [{title, folder, version}, ...] 仅含 [ 2 ] 谱面。"""
    current_folder: str | None = None
    entries: list[dict] = []

    for line in text.splitlines():
        header_folder = parse_version_header(line)
        if header_folder:
            current_folder = header_folder
            continue
        if not current_folder:
            continue
        title = extract_chart2_title_from_row(line)
        if not title:
            continue
        entries.append(
            {
                "title": title,
                "folder": current_folder,
                "version": current_folder,
            }
        )
    return entries


def load_atwiki_ordered_text(path: Path | None = None) -> str:
    if path and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    bundled = Path(__file__).resolve().parents[2] / "data" / "atwiki_ordered_by_version.txt"
    if bundled.is_file():
        return bundled.read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError("未找到 atwiki Ordered by Version 缓存文本")
