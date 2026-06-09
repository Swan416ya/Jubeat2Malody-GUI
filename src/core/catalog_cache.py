"""
曲库扫描结果磁盘缓存 — 避免每次启动都重新扫描游戏目录。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .song_catalog import CatalogEntry, find_extracted_song_dir
from .song_database import _METADATA_TSV
from .unpacker import find_metadata_xml

CACHE_VERSION = 1
_CACHE_DIR = Path.home() / ".jubeat2malody"
_CACHE_FILE = _CACHE_DIR / "catalog_cache.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _music_info_mtime(data_dir: Path) -> float:
    music_info_path = find_metadata_xml(data_dir, "music_info.xml")
    if music_info_path and music_info_path.is_file():
        return music_info_path.stat().st_mtime
    return 0.0


def _metadata_tsv_mtime() -> float:
    return _METADATA_TSV.stat().st_mtime if _METADATA_TSV.is_file() else 0.0


def compute_fingerprint(data_dir: Path, *, ifs_count: int = 0, ifs_newest_mtime: float = 0.0) -> Dict[str, Any]:
    """生成曲库缓存指纹。完整扫描时可附带 IFS 统计供展示。"""
    data_dir = data_dir.resolve()
    return {
        "data_dir": str(data_dir),
        "music_info_mtime": _music_info_mtime(data_dir),
        "metadata_tsv_mtime": _metadata_tsv_mtime(),
        "ifs_count": ifs_count,
        "ifs_newest_mtime": ifs_newest_mtime,
    }


def cache_still_valid(cached_fp: Dict[str, Any], data_dir: Path) -> bool:
    """启动时快速校验缓存（不 rglob 游戏目录）。"""
    data_dir = data_dir.resolve()
    if cached_fp.get("data_dir") != str(data_dir):
        return False
    return (
        cached_fp.get("music_info_mtime") == _music_info_mtime(data_dir)
        and cached_fp.get("metadata_tsv_mtime") == _metadata_tsv_mtime()
    )


def _entry_to_dict(entry: CatalogEntry) -> dict:
    return {
        "music_id": entry.music_id,
        "title": entry.title,
        "artist": entry.artist,
        "bpm": entry.bpm,
        "levels": entry.levels,
        "ifs_path": str(entry.ifs_path),
        "has_jacket": entry.has_jacket,
        "encrypted": entry.encrypted,
    }


def _entry_from_dict(data: dict) -> CatalogEntry:
    return CatalogEntry(
        music_id=int(data["music_id"]),
        title=data.get("title", ""),
        artist=data.get("artist", ""),
        bpm=data.get("bpm", ""),
        levels=dict(data.get("levels", {})),
        ifs_path=Path(data["ifs_path"]),
        has_jacket=bool(data.get("has_jacket")),
        encrypted=bool(data.get("encrypted")),
        extracted_dir=None,
    )


def refresh_extracted_status(
    entries: List[CatalogEntry], output_dir: Optional[Path]
) -> None:
    """根据当前输出目录更新「已提取」状态（快速，不重新扫游戏盘）。"""
    if not output_dir:
        for entry in entries:
            entry.extracted_dir = None
        return
    for entry in entries:
        entry.extracted_dir = find_extracted_song_dir(output_dir, entry.music_id)


def save_catalog_cache(
    data_dir: Path,
    entries: List[CatalogEntry],
    jacket_index: Dict[int, Path],
) -> bool:
    """写入曲库缓存。"""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ifs_newest = 0.0
        for entry in entries:
            try:
                ifs_newest = max(ifs_newest, entry.ifs_path.stat().st_mtime)
            except OSError:
                pass
        fp = compute_fingerprint(
            data_dir, ifs_count=len(entries), ifs_newest_mtime=ifs_newest,
        )
        payload = {
            "version": CACHE_VERSION,
            "cached_at": _utc_now_iso(),
            "fingerprint": fp,
            "entries": [_entry_to_dict(e) for e in entries],
            "jacket_index": {str(k): str(v) for k, v in jacket_index.items()},
        }
        tmp = _CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CACHE_FILE)
        return True
    except OSError:
        return False


def load_catalog_cache(
    data_dir: Path,
    output_dir: Optional[Path] = None,
) -> Optional[Tuple[List[CatalogEntry], Dict[int, Path], Dict[str, Any]]]:
    """读取曲库缓存；指纹不匹配或文件不存在时返回 None。"""
    if not _CACHE_FILE.is_file():
        return None

    try:
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("version") != CACHE_VERSION:
        return None

    cached_fp = payload.get("fingerprint", {})
    if not cache_still_valid(cached_fp, data_dir):
        return None

    entries = [_entry_from_dict(item) for item in payload.get("entries", [])]
    refresh_extracted_status(entries, output_dir)

    jacket_index: Dict[int, Path] = {}
    for key, value in payload.get("jacket_index", {}).items():
        try:
            jacket_index[int(key)] = Path(value)
        except ValueError:
            continue

    meta = {
        "cached_at": payload.get("cached_at", ""),
        "from_cache": True,
    }
    return entries, jacket_index, meta


def cache_path() -> Path:
    return _CACHE_FILE
