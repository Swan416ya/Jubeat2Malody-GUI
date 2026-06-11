"""乐曲初出版本 → mcz-releases 目录映射（来源：atwiki sonicy_memo Ordered by Version）。"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .atwiki_parser import is_chart2_title

_DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "song_debut_versions.json"

# atwiki: https://w.atwiki.jp/sonicy_memo/pages/4.html
ATWIKI_VERSION_SOURCE = "https://w.atwiki.jp/sonicy_memo/pages/4.html"

_CHART2_SUFFIX_RE = re.compile(r"\s*\[\s*2\s*\]\s*$")


def make_lookup_key(text: str, *, chart2: bool | None = None) -> str:
    """生成 song_debut_versions.json 索引键。"""
    text = (text or "").strip()
    is_c2 = is_chart2_title(text) if chart2 is None else chart2
    if not is_c2:
        text = _CHART2_SUFFIX_RE.sub("", text)
    else:
        text = _CHART2_SUFFIX_RE.sub(" [ 2 ]", text)
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text).lower()


def normalize_title(text: str) -> str:
    """兼容旧调用：普通曲名查找（剥除 [ 2 ]）。"""
    return make_lookup_key(text, chart2=False)


@lru_cache(maxsize=1)
def load_debut_index() -> dict[str, dict]:
    if not _DATA_FILE.is_file():
        return {}
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))


def resolve_debut_folder_from_mcz_stem(stem: str) -> Optional[str]:
    """从 .mcz 文件名（无扩展名）解析版本目录。"""
    if not stem:
        return None
    folder = resolve_debut_folder(stem)
    if folder:
        return folder
    if stem.endswith(" [ 2 ]"):
        return resolve_debut_folder(stem)
    if "_2_" in stem or stem.endswith("_2"):
        guess = stem.replace("_2_", " [ 2 ]").replace("_2", " [ 2 ]").replace("_", " ")
        return resolve_debut_folder(guess)
    return None


def resolve_debut_folder(title: str) -> Optional[str]:
    """按曲名查初出版本对应的 Branch 子目录 slug。

    带 [ 2 ] 的二谱按追加版本归类，不回退到原曲初版。
    """
    if not title:
        return None
    idx = load_debut_index()
    chart2 = is_chart2_title(title)
    for variant in (title, title.replace("_", "'"), title.replace("'", "_")):
        key = make_lookup_key(variant, chart2=chart2)
        entry = idx.get(key)
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
