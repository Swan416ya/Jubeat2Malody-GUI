#!/usr/bin/env python3
"""检查指定初版版本：本地可提取 vs Branch 已有 MCZ。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.malody_writer import mcz_safe_filename
from core.song_catalog import scan_game_catalog
from core.song_debut import resolve_debut_folder_for_id
from core.unpacker import find_metadata_xml, load_music_info, load_word_dictionary, load_word_info

DATA = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")


def _stem_variants(stem: str) -> set[str]:
    return {stem, stem.replace("_", "'"), stem.replace("'", "_")}


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else "jubeat-ave"
    wp = find_metadata_xml(DATA, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mi = load_music_info(find_metadata_xml(DATA, "music_info.xml"), word_dict=wd)
    wi = load_word_info(wp) if wp else {}
    entries = scan_game_catalog(DATA, None, music_info=mi, word_info=wi, word_dict=wd)
    target = [
        e
        for e in entries
        if resolve_debut_folder_for_id(e.music_id, e.title) == folder
        and not e.content_removed
    ]
    dest = BRANCH / folder
    existing: set[str] = set()
    if dest.is_dir():
        for p in dest.glob("*.mcz"):
            existing |= _stem_variants(p.stem)
    missing = [
        e
        for e in target
        if e.title not in existing and mcz_safe_filename(e.title) not in existing
    ]
    print(f"folder={folder} available={len(target)} branch={len(list(dest.glob('*.mcz'))) if dest.is_dir() else 0} missing={len(missing)}")
    for e in missing:
        print(f"  {e.music_id}\t{e.title}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
