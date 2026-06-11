#!/usr/bin/env python3
"""从 atwiki 文本合并 [ 2 ] 二谱追加版本映射到 song_debut_versions.json。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.atwiki_parser import load_atwiki_ordered_text, parse_chart2_debut_entries
from core.song_debut import make_lookup_key

DATA = ROOT / "data" / "song_debut_versions.json"
ATWIKI_CACHE = ROOT / "data" / "atwiki_ordered_by_version.txt"
AGENT_CACHE = Path(
    r"C:\Users\34470\.cursor\projects\e-Python-Project-Jubeat2Malody-GUI"
    r"\agent-tools\1bd1646d-afb5-4b8d-994f-299e19ad5eaa.txt"
)


def main() -> int:
    src = ATWIKI_CACHE if ATWIKI_CACHE.is_file() else AGENT_CACHE
    if not ATWIKI_CACHE.is_file() and AGENT_CACHE.is_file():
        ATWIKI_CACHE.write_text(AGENT_CACHE.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        src = ATWIKI_CACHE
        print(f"已固化 atwiki 缓存 -> {ATWIKI_CACHE}")

    text = load_atwiki_ordered_text(src)
    chart2 = parse_chart2_debut_entries(text)
    index = json.loads(DATA.read_text(encoding="utf-8"))

    added = updated = 0
    for entry in chart2:
        key = make_lookup_key(entry["title"], chart2=True)
        if key in index:
            if index[key].get("folder") != entry["folder"]:
                updated += 1
        else:
            added += 1
        index[key] = entry

    DATA.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ 2 ] 谱面: atwiki {len(chart2)} 条 | 新增 {added} | 更新 {updated} | 索引共 {len(index)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
