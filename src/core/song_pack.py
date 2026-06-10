"""
解包产物识别 — 自动区分街机 (EVE) 与国服 (MIDI) 并加载对应谱面。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from jubeatools import song

from .eve_parser import load_eve_song
from .song_resources import resolve_eve_map

SongSource = Literal["arcade", "cn", "unknown"]


def detect_song_source(song_dir: Path) -> SongSource:
    if not song_dir.is_dir():
        return "unknown"

    if resolve_eve_map(song_dir):
        return "arcade"

    for name in ("bsc.mid", "adv.mid", "ext.mid", "chart.mid"):
        if (song_dir / name).is_file():
            return "cn"

    info_path = song_dir / "song_info.txt"
    if info_path.is_file():
        text = info_path.read_text(encoding="utf-8", errors="replace")
        if "Jubeat CN" in text or "Chart Format: MIDI" in text:
            return "cn"
        if ".eve" in text.lower():
            return "arcade"

    return "unknown"


def source_label(source: SongSource) -> str:
    return {"arcade": "街机/日服", "cn": "国服", "unknown": "未知"}[source]


def load_chart_song(song_dir: Path, beat_snap: int = 4) -> song.Song:
    source = detect_song_source(song_dir)
    if source == "cn":
        from .cn_midi import load_cn_song

        return load_cn_song(song_dir, beat_snap=beat_snap)
    if source == "arcade":
        return load_eve_song(song_dir, beat_snap=beat_snap)
    raise ValueError("无法识别谱面格式：需要 .eve 或 .mid 文件")
