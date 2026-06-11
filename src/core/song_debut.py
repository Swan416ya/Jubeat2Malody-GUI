"""乐曲初出版本 → mcz-releases 目录映射（来源：atwiki sonicy_memo Ordered by Version）。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "song_debut_versions.json"

# atwiki: https://w.atwiki.jp/sonicy_memo/pages/4.html
ATWIKI_VERSION_SOURCE = "https://w.atwiki.jp/sonicy_memo/pages/4.html"


def normalize_title(text: str) -> str:
    text = re.sub(r"\s*\[\s*2\s*\]\s*$", "", (text or "").strip())
    return re.sub(r"\s+", "", text).lower()


@lru_cache(maxsize=1)
def load_debut_index() -> dict[str, dict]:
    if not _DATA_FILE.is_file():
        return {}
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))


def resolve_debut_folder(title: str) -> Optional[str]:
    """按曲名查初出版本对应的 Branch 子目录 slug。"""
    if not title:
        return None
    idx = load_debut_index()
    for variant in (title, title.replace("_", "'"), title.replace("'", "_")):
        entry = idx.get(normalize_title(variant))
        if entry:
            return entry.get("folder")
    return None


def resolve_debut_folder_for_id(music_id: int, title: str = "") -> Optional[str]:
    """优先曲名，回退 metadata TSV。"""
    folder = resolve_debut_folder(title)
    if folder:
        return folder
    if music_id <= 0:
        return None
    try:
        from .song_database import get_reference_song_name

        ref = get_reference_song_name(music_id)
        if ref:
            return resolve_debut_folder(ref)
    except Exception:
        pass
    return None


def iter_beyond_ave_titles() -> list[str]:
    """返回映射为 jubeat-beyond-ave 的全部曲名。"""
    return sorted(
        entry["title"]
        for entry in load_debut_index().values()
        if entry.get("folder") == "jubeat-beyond-ave"
    )
