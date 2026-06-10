"""国服曲库缓存。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .cn_catalog import CnCatalogEntry, resolve_cn_data_dir
from .song_catalog import find_extracted_song_dir

CACHE_VERSION = 1
_CACHE_DIR = Path.home() / ".jubeat2malody"
_CACHE_FILE = _CACHE_DIR / "cn_catalog_cache.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bundle_fingerprint(data_dir: Path) -> Dict[str, Any]:
    hotupdate = resolve_cn_data_dir(data_dir)
    if not hotupdate:
        return {"data_dir": str(data_dir), "hotupdate": "", "bundle_count": 0}
    bundles = list(hotupdate.glob("assets_bundles_*"))
    newest = max((p.stat().st_mtime for p in bundles), default=0.0)
    return {
        "data_dir": str(data_dir.resolve()),
        "hotupdate": str(hotupdate.resolve()),
        "bundle_count": len(bundles),
        "newest_mtime": newest,
    }


def cache_still_valid(cached_fp: Dict[str, Any], data_dir: Path) -> bool:
    return cached_fp == _bundle_fingerprint(data_dir)


def _entry_to_dict(entry: CnCatalogEntry) -> dict:
    return {
        "music_id": entry.music_id,
        "title": entry.title,
        "artist": entry.artist,
        "bpm": entry.bpm,
        "levels": entry.levels,
        "has_bgm": entry.has_bgm,
        "has_chart": entry.has_chart,
        "has_jacket": entry.has_jacket,
    }


def _entry_from_dict(data: dict) -> CnCatalogEntry:
    return CnCatalogEntry(
        music_id=int(data["music_id"]),
        title=data.get("title", ""),
        artist=data.get("artist", ""),
        bpm=data.get("bpm", ""),
        levels=dict(data.get("levels", {})),
        has_bgm=bool(data.get("has_bgm")),
        has_chart=bool(data.get("has_chart")),
        has_jacket=bool(data.get("has_jacket")),
    )


def save_cn_catalog_cache(data_dir: Path, entries: List[CnCatalogEntry]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CACHE_VERSION,
        "cached_at": _utc_now_iso(),
        "fingerprint": _bundle_fingerprint(data_dir),
        "entries": [_entry_to_dict(e) for e in entries],
    }
    _CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cn_catalog_cache(
    data_dir: Path,
    output_dir: Optional[Path] = None,
) -> Optional[Tuple[List[CnCatalogEntry], dict]]:
    if not _CACHE_FILE.is_file():
        return None
    try:
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("version") != CACHE_VERSION:
        return None
    fp = payload.get("fingerprint", {})
    if not cache_still_valid(fp, data_dir):
        return None

    entries = [_entry_from_dict(d) for d in payload.get("entries", [])]
    if output_dir:
        refresh_cn_extracted_status(entries, output_dir)
    meta = {"cached_at": payload.get("cached_at", ""), "from_cache": True}
    return entries, meta


def refresh_cn_extracted_status(entries: List[CnCatalogEntry], output_dir: Path) -> None:
    if not output_dir or not output_dir.is_dir():
        return
    for entry in entries:
        entry.extracted_dir = find_extracted_song_dir(output_dir, entry.music_id)
