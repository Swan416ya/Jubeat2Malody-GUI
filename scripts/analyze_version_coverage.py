#!/usr/bin/env python3
"""分析某版本初版曲：映射总数 vs 本地数据 vs 版权移除。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.malody_writer import mcz_safe_filename
from core.song_catalog import scan_game_catalog
from core.song_debut import load_debut_index, resolve_debut_folder_for_id
from core.unpacker import find_metadata_xml, load_music_info, load_word_dictionary, load_word_info

DATA = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
DEBUT = ROOT / "data" / "song_debut_versions.json"


def _titles_in_mapping(folder: str) -> list[dict]:
    idx = load_debut_index()
    return sorted(
        [v for v in idx.values() if v.get("folder") == folder],
        key=lambda x: x.get("title", ""),
    )


def main() -> int:
    folders = sys.argv[1:] if len(sys.argv) > 1 else [
        "jubeat-ripples",
        "jubeat-ripples-append",
    ]

    wp = find_metadata_xml(DATA, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(DATA, "music_info.xml")
    mi = load_music_info(mp, word_dict=wd) if mp else {}
    wi = load_word_info(wp) if wp else {}
    entries = scan_game_catalog(DATA, None, music_info=mi, word_info=wi, word_dict=wd)

    by_folder: dict[str, list] = {f: [] for f in folders}
    for e in entries:
        folder = resolve_debut_folder_for_id(e.music_id, e.title)
        if folder in by_folder:
            by_folder[folder].append(e)

    for folder in folders:
        mapped = _titles_in_mapping(folder)
        local = by_folder.get(folder, [])
        available = [e for e in local if not e.content_removed]
        removed = [e for e in local if e.content_removed]

        mapped_titles = {m["title"] for m in mapped}
        local_titles = {e.title for e in local}
        available_titles = {e.title for e in available}

        missing_no_data = [
            m for m in mapped if m["title"] not in local_titles
        ]
        missing_removed = [
            e for e in removed if e.title in mapped_titles
        ]

        branch = BRANCH / folder
        mcz_n = len(list(branch.glob("*.mcz"))) if branch.is_dir() else 0

        print("=" * 60)
        print(folder)
        print(f"  atwiki 初版映射:     {len(mapped)} 首")
        print(f"  本地有 IFS 数据:     {len(local)} 首")
        print(f"    可提取:            {len(available)} 首")
        print(f"    版权到期(占位):    {len(removed)} 首")
        print(f"  映射有但本地无数据:  {len(missing_no_data)} 首")
        print(f"  Branch MCZ:          {mcz_n} 个")

        if removed:
            print(f"\n  [版权到期 — 本地有占位 IFS，无法提取]")
            for e in sorted(removed, key=lambda x: x.music_id):
                print(f"    {e.music_id}\t{e.title}")

        if missing_no_data:
            print(f"\n  [映射有 — 本地 Beyond Ave 安装目录无 IFS]")
            for m in missing_no_data[:40]:
                print(f"    ?\t{m['title']}")
            if len(missing_no_data) > 40:
                print(f"    ... 还有 {len(missing_no_data) - 40} 首")

        # 本地有数据但不在映射（少见）
        extra = [e for e in local if e.title not in mapped_titles]
        if extra:
            print(f"\n  [本地有数据但映射未收录] {len(extra)} 首")
            for e in extra[:10]:
                print(f"    {e.music_id}\t{e.title}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
