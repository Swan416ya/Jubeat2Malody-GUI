"""
游戏曲库扫描 — 不解包即可列出全部可提取乐曲。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .unpacker import (
    REMOVED_SONG_STATUS,
    _finalize_song_info,
    _folder_display_name,
    _parse_music_id_from_ifs,
    _safe_folder_name,
    build_jacket_index,
    find_metadata_xml,
    is_ifs_content_removed,
    load_music_info,
    load_word_dictionary,
    load_word_info,
    resolve_artist,
    resolve_bpm,
    resolve_display_title,
)


@dataclass
class CatalogEntry:
    music_id: int
    title: str
    artist: str
    bpm: str
    levels: Dict[str, str] = field(default_factory=dict)
    ifs_path: Path = field(default_factory=Path)
    has_jacket: bool = False
    content_removed: bool = False
    extracted_dir: Optional[Path] = None

    @property
    def status(self) -> str:
        if self.content_removed:
            return REMOVED_SONG_STATUS
        if self.extracted_dir:
            return "已提取"
        return "未提取"


def find_extracted_song_dir(output_base: Path, music_id: int) -> Optional[Path]:
    """在输出目录中查找已解包的单曲文件夹。"""
    if not output_base.is_dir():
        return None
    prefix = f"{music_id}_"
    matches = [
        d for d in output_base.iterdir()
        if d.is_dir() and d.name.startswith(prefix) and (d / "song_info.txt").is_file()
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def scan_game_catalog(
    data_dir: Path,
    output_dir: Optional[Path] = None,
    *,
    jacket_index: Optional[dict[int, Path]] = None,
    music_info: Optional[dict] = None,
    word_info: Optional[dict] = None,
    word_dict: Optional[dict] = None,
) -> List[CatalogEntry]:
    """扫描游戏数据目录，返回曲库列表（不执行解包）。"""
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        return []

    if music_info is None:
        music_info_path = find_metadata_xml(data_dir, "music_info.xml")
        if word_dict is None:
            word_info_path = find_metadata_xml(data_dir, "word_info.xml")
            word_dict = load_word_dictionary(word_info_path) if word_info_path else {}
        music_info = (
            load_music_info(music_info_path, word_dict=word_dict)
            if music_info_path else {}
        )

    if word_info is None:
        word_info_path = find_metadata_xml(data_dir, "word_info.xml")
        word_info = load_word_info(word_info_path) if word_info_path else {}

    if jacket_index is None:
        jacket_index = build_jacket_index(data_dir)

    ifs_files = sorted(data_dir.rglob("*_msc.ifs"))
    entries: List[CatalogEntry] = []

    for ifs_path in ifs_files:
        music_id = _parse_music_id_from_ifs(ifs_path)
        if music_id <= 0:
            continue

        raw = music_info.get(music_id, {})
        song_info = _finalize_song_info(raw, music_id, word_info)
        title = resolve_display_title(song_info) or song_info.get("name") or f"unknown_{music_id}"
        artist = resolve_artist(song_info) or song_info.get("artist", "")
        bpm_val = resolve_bpm(song_info)
        bpm = str(bpm_val) if bpm_val > 0 else ""

        levels: Dict[str, str] = {}
        for diff, lev in song_info.get("levels", {}).items():
            if isinstance(lev, dict):
                levels[diff.upper()] = str(lev.get("level", "-"))
            else:
                levels[diff.upper()] = str(lev)

        extracted = find_extracted_song_dir(output_dir, music_id) if output_dir else None

        entries.append(CatalogEntry(
            music_id=music_id,
            title=title,
            artist=artist,
            bpm=bpm,
            levels=levels,
            ifs_path=ifs_path,
            has_jacket=music_id in jacket_index,
            content_removed=is_ifs_content_removed(ifs_path),
            extracted_dir=extracted,
        ))

    entries.sort(key=lambda e: e.music_id)
    return entries
