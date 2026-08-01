"""为指定歌曲目录生成 .mc 字节并落盘到 debug 路径，用于 before/after 对比。

用法：
    python scripts/dump_one_mc.py <song_dir> <out_mc_path>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.song_pack import detect_song_source, load_chart_song, resolve_mapper
from src.core.malody_writer import (
    MALODY_BEAT_SNAP,
    _generate_mc_bytes,
    _metadata_from_info,
    _resolve_timing,
    _level_for_diff,
    parse_song_info,
)


def main(song_dir: Path, out_path: Path):
    info_path = song_dir / "song_info.txt"
    info = parse_song_info(info_path)
    jt_song = load_chart_song(song_dir, beat_snap=MALODY_BEAT_SNAP)
    jt_song.metadata = _metadata_from_info(info, None, None)
    source = detect_song_source(song_dir)
    mapper = resolve_mapper(source)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for diff_name, chart, timing in jt_song.iter_charts_with_applicable_timing():
        resolved_timing = _resolve_timing(timing, info)
        level = _level_for_diff(info, diff_name)
        mc_bytes = _generate_mc_bytes(
            jt_song.metadata, diff_name, chart, resolved_timing,
            audio_filename="bgm.ogg", level=level,
            cover_filename=None, creator=mapper,
        )
        out_file = out_path.with_name(f"{out_path.stem}.{diff_name}.mc")
        out_file.write_bytes(mc_bytes)
        written.append(out_file)
        print(f"wrote {out_file} ({len(mc_bytes)} bytes)")
    return written


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
