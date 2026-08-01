#!/usr/bin/env python3
"""Beyond Ave 本地数据 → Branch：补全尚未转换的 MCZ（按初版/追加版本归类）。

从当前 Beyond Ave 街机数据目录扫描全部可提取曲目，跳过 Branch 对应版本文件夹
里已有的 MCZ，增量解包并转换。终端实时显示进度条与 ETA。

用法:
  python -u scripts/batch_beyond_ave_mcz.py
  python -u scripts/batch_beyond_ave_mcz.py --folder jubeat-beyond-ave
  python -u scripts/batch_beyond_ave_mcz.py --folder jubeat-ave jubeat-beyond-ave
  python -u scripts/batch_beyond_ave_mcz.py --fresh --folder jubeat-beyond-ave
  python -u scripts/batch_beyond_ave_mcz.py "D:/jubeat/data"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.malody_writer import convert_song, mcz_safe_filename
from core.song_catalog import find_extracted_song_dir, scan_game_catalog
from core.song_debut import resolve_debut_folder_for_id
from core.song_pack import detect_song_source
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
EXTRACT_DIR = ROOT / "debug_out" / "beyond_ave_extract"
MCZ_TEMP = ROOT / "debug_out" / "beyond_ave_mcz"
REPORT_PATH = ROOT / "debug_out" / "beyond_ave_mcz_report.json"

SKIP_BRANCH_DIRS = frozenset({"音乐魔方"})


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


def _fmt_eta(seconds: float) -> str:
    if seconds < 0 or not (seconds < 1e9):
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _progress_bar(done: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "[" + " " * width + "]"
    filled = int(width * done / total)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


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


def _stem_variants(stem: str) -> set[str]:
    return {stem, stem.replace("_", "'"), stem.replace("'", "_")}


def _collect_existing_by_folder() -> dict[str, set[str]]:
    by_folder: dict[str, set[str]] = {}
    if not BRANCH_ROOT.is_dir():
        return by_folder
    for dest in BRANCH_ROOT.iterdir():
        if not dest.is_dir() or dest.name in SKIP_BRANCH_DIRS:
            continue
        stems: set[str] = set()
        for p in dest.glob("*.mcz"):
            stems |= _stem_variants(p.stem)
        by_folder[dest.name] = stems
    return by_folder


def _is_done(title: str, existing: set[str]) -> bool:
    return title in existing or mcz_safe_filename(title) in existing


def _find_extracted(mid: int) -> Path | None:
    for base in (EXTRACT_DIR, ROOT / "debug_out"):
        found = find_extracted_song_dir(base, mid)
        if found:
            return found
    return None


def _purge_extracted(mid: int) -> None:
    prefix = f"{mid}_"
    for base in (EXTRACT_DIR, ROOT / "debug_out"):
        if not base.is_dir():
            continue
        for d in list(base.iterdir()):
            if d.is_dir() and d.name.startswith(prefix):
                shutil.rmtree(d, ignore_errors=True)


def _load_catalog(data_dir: Path) -> list:
    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    mi = load_music_info(mp, word_dict=wd) if mp else {}
    wi = load_word_info(wp) if wp else {}
    return scan_game_catalog(data_dir, EXTRACT_DIR, music_info=mi, word_info=wi, word_dict=wd)


def _classify_entries(
    entries: list,
    *,
    folder_filter: set[str] | None,
) -> tuple[list, dict]:
    """返回 (可处理条目, 统计信息)。"""
    stats = {
        "content_removed": 0,
        "unknown_folder": 0,
        "filtered_out": 0,
        "available": 0,
    }
    targets: list[tuple[object, str]] = []
    for entry in entries:
        if entry.content_removed:
            stats["content_removed"] += 1
            continue
        folder = resolve_debut_folder_for_id(entry.music_id, entry.title)
        if not folder or folder == "unknown":
            stats["unknown_folder"] += 1
            continue
        if folder_filter and folder not in folder_filter:
            stats["filtered_out"] += 1
            continue
        stats["available"] += 1
        targets.append((entry, folder))
    targets.sort(key=lambda x: (x[1], x[0].music_id))
    return targets, stats


def _clear_folders(folders: set[str]) -> int:
    cleared = 0
    for name in folders:
        dest = BRANCH_ROOT / name
        if not dest.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        for mcz in dest.glob("*.mcz"):
            mcz.unlink()
            cleared += 1
    return cleared


def _process_one(
    entry,
    folder: str,
    *,
    music_info: dict,
    word_info: dict,
    jacket_index: dict,
    force_extract: bool,
) -> tuple[bool, str]:
    mid = entry.music_id
    title = entry.title

    song_dir = None if force_extract else (entry.extracted_dir or _find_extracted(mid))
    if song_dir and (song_dir / "song_info.txt").is_file():
        if detect_song_source(song_dir) != "arcade":
            song_dir = None

    if not song_dir:
        if force_extract:
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
    else:
        _safe_print(f"    使用已解包目录: {song_dir.name}")

    if not song_dir:
        return False, "解包失败"

    _safe_print("    转换 MCZ ...")
    mcz = convert_song(song_dir, MCZ_TEMP, skip_existing=False)
    if not mcz or not _charts_distinct(mcz):
        if mcz:
            mcz.unlink(missing_ok=True)
        return False, "转换失败或谱面异常"

    dest_dir = BRANCH_ROOT / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / mcz.name
    shutil.copy2(mcz, dest)
    return True, f"{folder}/{dest.name}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Beyond Ave 本地数据补全 Branch 缺失 MCZ（增量，带进度）"
    )
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=str(DEFAULT_DATA_DIR),
        help="游戏数据目录 (默认 Beyond Ave contents/data)",
    )
    parser.add_argument(
        "--folder",
        nargs="+",
        metavar="NAME",
        help="仅处理指定版本文件夹，如 jubeat-beyond-ave jubeat-ave",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="清空 --folder 指定目录（未指定则清空本次涉及的全部版本目录）后全量重跑",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        _safe_print(f"错误: 游戏数据目录不存在: {data_dir}")
        return 1

    folder_filter = set(args.folder) if args.folder else None

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP.mkdir(parents=True, exist_ok=True)
    BRANCH_ROOT.mkdir(parents=True, exist_ok=True)

    _safe_print("=" * 60)
    _safe_print("Beyond Ave 本地数据 → Branch MCZ（增量补全）")
    _safe_print(f"数据目录: {data_dir}")
    _safe_print(f"输出目录: {BRANCH_ROOT}")
    if folder_filter:
        _safe_print(f"版本过滤: {', '.join(sorted(folder_filter))}")
    else:
        _safe_print("版本过滤: 全部（按初版/追加版本自动归类）")
    _safe_print("扫描曲库 ...")

    entries = _load_catalog(data_dir)
    classified, scan_stats = _classify_entries(entries, folder_filter=folder_filter)

    existing_by_folder = _collect_existing_by_folder()
    pending: list[tuple[object, str]] = []
    skip_count = 0
    for entry, folder in classified:
        existing = existing_by_folder.get(folder, set())
        if args.fresh or not _is_done(entry.title, existing):
            pending.append((entry, folder))
        else:
            skip_count += 1

    involved_folders = {folder for _, folder in classified}
    cleared = 0
    if args.fresh and involved_folders:
        cleared = _clear_folders(involved_folders)
        pending = classified
        skip_count = 0

    pending_by_folder: dict[str, int] = {}
    for _, folder in pending:
        pending_by_folder[folder] = pending_by_folder.get(folder, 0) + 1

    _safe_print(
        f"扫描 {len(entries)} 条 | 可提取 {scan_stats['available']} | "
        f"版权占位 {scan_stats['content_removed']} | "
        f"未映射版本 {scan_stats['unknown_folder']}"
    )
    if args.fresh:
        _safe_print(f"模式: 全量重跑（已清空 {cleared} 个旧 MCZ）")
    else:
        _safe_print(f"模式: 增量（已有跳过 {skip_count} 首）")
    _safe_print(f"待处理: {len(pending)} 首")
    for name in sorted(pending_by_folder):
        branch_n = len(list((BRANCH_ROOT / name).glob("*.mcz"))) if (BRANCH_ROOT / name).is_dir() else 0
        _safe_print(f"  {name}: 待处理 {pending_by_folder[name]} | Branch 现有 {branch_n}")
    _safe_print("=" * 60)

    if not pending:
        _safe_print("无需处理，已全部完成。")
        return 0

    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    music_info = load_music_info(mp, word_dict=wd) if mp else {}
    word_info = load_word_info(wp) if wp else {}
    jacket_index = build_jacket_index(data_dir)

    ok_count = 0
    fail_count = 0
    t0 = time.time()
    report: dict = {
        "data_dir": str(data_dir),
        "folder_filter": sorted(folder_filter) if folder_filter else None,
        "fresh": args.fresh,
        "scan": scan_stats,
        "cleared": cleared,
        "skipped_existing": skip_count,
        "pending": len(pending),
        "pending_by_folder": pending_by_folder,
        "ok": [],
        "fail": [],
    }

    for idx, (entry, folder) in enumerate(pending, start=1):
        done = ok_count + fail_count
        remain = len(pending) - done
        elapsed = time.time() - t0
        eta = (elapsed / done * remain) if done > 0 else 0.0
        pct = 100.0 * done / len(pending)

        _safe_print(
            f"\n{_progress_bar(done, len(pending))} {pct:5.1f}% | "
            f"{idx}/{len(pending)} | "
            f"成功 {ok_count} 失败 {fail_count} 剩余 {remain} | "
            f"用时 {_fmt_eta(elapsed)} ETA {_fmt_eta(eta)}"
        )
        _safe_print(f"  >> [{folder}] {entry.title} ({entry.music_id})")

        try:
            ok, detail = _process_one(
                entry,
                folder,
                music_info=music_info,
                word_info=word_info,
                jacket_index=jacket_index,
                force_extract=args.fresh,
            )
        except Exception as exc:
            ok, detail = False, str(exc)

        if ok:
            ok_count += 1
            _safe_print(f"    OK  {detail}")
            report["ok"].append(
                {
                    "music_id": entry.music_id,
                    "title": entry.title,
                    "folder": folder,
                    "mcz": detail,
                }
            )
        else:
            fail_count += 1
            _safe_print(f"    FAIL  {detail}")
            report["fail"].append(
                {
                    "music_id": entry.music_id,
                    "title": entry.title,
                    "folder": folder,
                    "reason": detail,
                }
            )

    elapsed = time.time() - t0
    branch_totals = {
        name: len(list((BRANCH_ROOT / name).glob("*.mcz")))
        for name in sorted(involved_folders)
        if (BRANCH_ROOT / name).is_dir()
    }
    report["branch_totals"] = branch_totals
    report["elapsed_sec"] = round(elapsed, 1)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _safe_print("\n" + "=" * 60)
    _safe_print(
        f"完成: 本次成功 {ok_count}/{len(pending)} | 失败 {fail_count} | "
        f"跳过 {skip_count}"
    )
    for name, n in sorted(branch_totals.items()):
        _safe_print(f"  {name}: {n} 个 MCZ")
    _safe_print(f"耗时 {elapsed / 60:.1f} 分钟 | 报告: {REPORT_PATH}")
    _safe_print("=" * 60)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
