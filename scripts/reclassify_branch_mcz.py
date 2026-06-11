#!/usr/bin/env python3
"""按 atwiki 初版/二谱追加版本，重新归类 Branch 内全部 MCZ。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")

from core.song_debut import resolve_debut_folder_from_mcz_stem  # noqa: E402


def main() -> int:
    moves = 0
    for mcz in sorted(BRANCH.rglob("*.mcz")):
        if "音乐魔方" in mcz.parts:
            continue
        folder = resolve_debut_folder_from_mcz_stem(mcz.stem)
        if not folder:
            continue
        dest_dir = BRANCH / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / mcz.name
        if dest.resolve() == mcz.resolve():
            continue
        if dest.exists():
            mcz.unlink()
            print(f"删除重复: {mcz.name} (保留 {folder}/)")
        else:
            shutil.move(str(mcz), str(dest))
            print(f"移动: {mcz.parent.name}/{mcz.name} -> {folder}/")
        moves += 1
    print(f"完成，处理 {moves} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
