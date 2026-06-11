#!/usr/bin/env python3
"""日版初版曲全量重跑：清空目录 → 强制重解包 → 转 MCZ，终端实时显示进度。

默认处理 jubeat-ave + jubeat-beyond-ave。

用法:
  python scripts/batch_rerun_arcade_versions.py
  python scripts/batch_rerun_arcade_versions.py jubeat-ave
  python scripts/batch_rerun_arcade_versions.py jubeat-ave jubeat-beyond-ave
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.malody_writer import convert_song
from core.song_catalog import scan_game_catalog
from core.song_debut import resolve_debut_folder_for_id
from core.unpacker import (
    build_jacket_index,
    extract_song,
    find_metadata_xml,
    load_music_info,
    load_word_dictionary,
    load_word_info,
)

DEFAULT_DATA_DIR = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH_ROOT = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
EXTRACT_DIR = ROOT / "debug_out" / "arcade_rerun_extract"
MCZ_TEMP = ROOT / "debug_out" / "arcade_rerun_mcz"
DEFAULT_FOLDERS = ("jubeat-ave", "jubeat-beyond-ave")


def _safe_print(*args, **kwargs) -> None:
    kwargs.setdefault("flush", True)
    text = " ".join(str(a) for a in args)
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        print(
            text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"),
            **kwargs,
        )


def _charts_distinct(mcz: Path) -> bool:
    with zipfile.ZipFile(mcz) as zf:
        sigs: set[str] = set()
        for name in zf.namelist():
            if not name.endswith(".mc"):
                continue
            data = json.loads(zf.read(name).decode("utf-8"))
            notes = [
                (tuple(n["beat"]), n["index"], tuple(n.get("endbeat", ())))
                for n in data.get("note", [])
                if "index" in n
            ]
            sigs.add(hashlib.md5(repr(sorted(notes)).encode()).hexdigest())
        return len(sigs) >= 1


def _purge_extracted(music_id: int) -> None:
    prefix = f"{music_id}_"
    for base in (EXTRACT_DIR, ROOT / "debug_out"):
        if not base.is_dir():
            continue
        for d in list(base.iterdir()):
            if d.is_dir() and d.name.startswith(prefix):
                shutil.rmtree(d, ignore_errors=True)


def _clear_branch_mcz(folder: str) -> int:
    dest = BRANCH_ROOT / folder
    if not dest.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for mcz in dest.glob("*.mcz"):
        mcz.unlink()
        removed += 1
    return removed


def _load_targets(data_dir: Path, folder: str) -> list:
    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    mi = load_music_info(mp, word_dict=wd) if mp else {}
    wi = load_word_info(wp) if wp else {}
    entries = scan_game_catalog(data_dir, None, music_info=mi, word_info=wi, word_dict=wd)
    return sorted(
        [
            e
            for e in entries
            if resolve_debut_folder_for_id(e.music_id, e.title) == folder
            and not e.content_removed
        ],
        key=lambda e: e.music_id,
    )


def _process_one(
    entry,
    data_dir: Path,
    folder: str,
    music_info: dict,
    word_info: dict,
    jacket_index: dict,
) -> tuple[bool, str]:
    mid = entry.music_id
    title = entry.title
    _purge_extracted(mid)
    _safe_print(f"    解包 {title} ({mid}) ...")
    song_dir = extract_song(
        entry.ifs_path,
        music_info,
        EXTRACT_DIR,
        ifs_dir=entry.ifs_path.parent,
        word_info=word_info,
        jacket_index=jacket_index,
    )
    if not song_dir:
        return False, "解包失败"

    mcz = convert_song(song_dir, MCZ_TEMP, skip_existing=False)
    if not mcz or not _charts_distinct(mcz):
        if mcz:
            mcz.unlink(missing_ok=True)
        return False, "转换失败或谱面异常"

    dest_dir = BRANCH_ROOT / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / mcz.name
    shutil.copy2(mcz, dest)
    return True, str(dest)


def _run_folder(data_dir: Path, folder: str, stats: dict) -> None:
    cleared = _clear_branch_mcz(folder)
    targets = _load_targets(data_dir, folder)
    total = len(targets)
    stats["cleared"][folder] = cleared
    stats["total"][folder] = total

    if total == 0:
        _safe_print(f"\n[{folder}] 无可用曲目，跳过")
        return

    _safe_print(f"\n{'=' * 60}")
    _safe_print(f"[{folder}] 清空旧 MCZ {cleared} 个 | 待处理 {total} 首")
    _safe_print(f"{'=' * 60}")

    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    music_info = load_music_info(mp, word_dict=wd) if mp else {}
    word_info = load_word_info(wp) if wp else {}
    jacket_index = build_jacket_index(data_dir)

    ok_count = 0
    fail_count = 0
    t0 = time.time()

    for idx, entry in enumerate(targets, start=1):
        done = ok_count + fail_count
        remain = total - done
        _safe_print(
            f"\n[{folder}] 进度 {idx}/{total} | "
            f"成功 {ok_count} | 失败 {fail_count} | 剩余 {remain} | "
            f"当前: {entry.title}"
        )
        try:
            ok, detail = _process_one(
                entry, data_dir, folder, music_info, word_info, jacket_index
            )
        except Exception as exc:
            ok, detail = False, str(exc)

        if ok:
            ok_count += 1
            _safe_print(f"    OK -> {detail}")
            stats["ok"].append({"folder": folder, "music_id": entry.music_id, "title": entry.title})
        else:
            fail_count += 1
            _safe_print(f"    FAIL: {detail}")
            stats["fail"].append(
                {
                    "folder": folder,
                    "music_id": entry.music_id,
                    "title": entry.title,
                    "reason": detail,
                }
            )

    elapsed = time.time() - t0
    stats["done"][folder] = ok_count
    _safe_print(
        f"\n[{folder}] 完成: 成功 {ok_count}/{total} | 失败 {fail_count} | "
        f"耗时 {elapsed / 60:.1f} 分钟"
    )


def main() -> int:
    folders = list(sys.argv[1:]) if len(sys.argv) > 1 else list(DEFAULT_FOLDERS)
    data_dir = DEFAULT_DATA_DIR

    if not data_dir.is_dir():
        _safe_print(f"游戏数据目录不存在: {data_dir}")
        return 1

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP.mkdir(parents=True, exist_ok=True)

    stats: dict = {
        "folders": folders,
        "cleared": {},
        "total": {},
        "done": {},
        "ok": [],
        "fail": [],
    }

    _safe_print("日版初版曲全量重跑（含曲绘 BGR→RGB 修复）")
    _safe_print(f"数据目录: {data_dir}")
    _safe_print(f"输出目录: {BRANCH_ROOT}")
    _safe_print(f"目标版本: {', '.join(folders)}")

    for folder in folders:
        _run_folder(data_dir, folder, stats)

    report = ROOT / "debug_out" / "arcade_rerun_report.json"
    report.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    total_ok = sum(stats["done"].values())
    total_all = sum(stats["total"].values())
    total_fail = len(stats["fail"])
    _safe_print(f"\n{'=' * 60}")
    _safe_print(f"全部完成: 成功 {total_ok}/{total_all} | 失败 {total_fail}")
    _safe_print(f"报告: {report}")
    _safe_print(f"{'=' * 60}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
