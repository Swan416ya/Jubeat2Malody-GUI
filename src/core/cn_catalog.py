"""
国服曲库扫描 — 基于 Unity Bundle 索引，无需解包即可列出乐曲。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .cn_bundles import CnBundleIndex, find_cn_hotupdate_dir, is_cn_hotupdate_dir
from .song_catalog import find_extracted_song_dir


@dataclass
class CnCatalogEntry:
    music_id: int
    title: str
    artist: str
    bpm: str
    levels: Dict[str, str] = field(default_factory=dict)
    has_bgm: bool = False
    has_chart: bool = False
    has_jacket: bool = False
    extracted_dir: Optional[Path] = None

    @property
    def status(self) -> str:
        if self.extracted_dir:
            return "已提取"
        return "未提取"


def resolve_cn_data_dir(path: Path) -> Optional[Path]:
    path = Path(path)
    if is_cn_hotupdate_dir(path):
        return path
    return find_cn_hotupdate_dir(path)


def scan_cn_catalog(
    data_dir: Path,
    output_dir: Optional[Path] = None,
    *,
    index: Optional[CnBundleIndex] = None,
    progress=None,
) -> List[CnCatalogEntry]:
    hotupdate = resolve_cn_data_dir(data_dir)
    if not hotupdate:
        return []

    if index is None:
        index = CnBundleIndex.scan(hotupdate, progress=progress)

    entries: List[CnCatalogEntry] = []
    for music_id in index.music_ids:
        info = index.get_song_info(music_id)
        bpm_val = info.get("bpm_max") or info.get("bpm_min")
        bpm = str(bpm_val) if bpm_val else ""
        extracted = find_extracted_song_dir(output_dir, music_id) if output_dir else None
        entries.append(
            CnCatalogEntry(
                music_id=music_id,
                title=info.get("name") or str(music_id),
                artist=info.get("artist_name", ""),
                bpm=bpm,
                levels=dict(info.get("levels", {})),
                has_bgm=music_id in index.bgm,
                has_chart=music_id in index.chart_bundle_by_id,
                has_jacket=music_id in index.jackets,
                extracted_dir=extracted,
            )
        )

    entries.sort(key=lambda e: e.music_id)
    return entries
