#!/usr/bin/env python3
"""检查 Beyond Ave 初版曲本地可提取 vs Branch 已有 MCZ。"""
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
BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch\jubeat-beyond-ave")


def _stem_variants(stem: str) -> set[str]:
    return {stem, stem.replace("_", "'"), stem.replace("'", "_")}


def main() -> int:
    wp = find_metadata_xml(DATA, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mi = load_music_info(find_metadata_xml(DATA, "music_info.xml"), word_dict=wd)
    wi = load_word_info(wp) if wp else {}
    entries = scan_game_catalog(DATA, None, music_info=mi, word_info=wi, word_dict=wd)
    beyond = [
        e
        for e in entries
        if resolve_debut_folder_for_id(e.music_id, e.title) == "jubeat-beyond-ave"
        and not e.content_removed
    ]
    existing: set[str] = set()
    for p in BRANCH.glob("*.mcz"):
        existing |= _stem_variants(p.stem)

    missing = [
        e
        for e in beyond
        if e.title not in existing and mcz_safe_filename(e.title) not in existing
    ]
    print(f"available={len(beyond)} branch={len(list(BRANCH.glob('*.mcz')))} missing={len(missing)}")
    for e in missing:
        print(f"  {e.music_id}\t{e.title}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
