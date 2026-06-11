#!/usr/bin/env python3
"""jubeat-ripples / jubeat-ripples-append 初版曲批量转 MCZ（默认覆盖重跑）。

用于替换音频/曲绘修复前生成的旧 MCZ（如隅田川夏恋歌）。

用法:
  python -u scripts/batch_ripples_mcz.py
  python -u scripts/batch_ripples_mcz.py --no-fresh   # 增量，跳过已有
  python -u scripts/batch_ripples_mcz.py --folders jubeat-ripples  # 只跑 ripples
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

DEFAULT_FOLDERS = ("jubeat-ripples", "jubeat-ripples-append")
DEFAULT_DATA_DIR = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH_ROOT = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
EXTRACT_DIR = ROOT / "debug_out" / "ripples_extract"
MCZ_TEMP = ROOT / "debug_out" / "ripples_mcz"
REPORT_PATH = ROOT / "debug_out" / "ripples_mcz_report.json"


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


def _load_targets(data_dir: Path, folder: str) -> list:
    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    mi = load_music_info(mp, word_dict=wd) if mp else {}
    wi = load_word_info(wp) if wp else {}
    entries = scan_game_catalog(data_dir, EXTRACT_DIR, music_info=mi, word_info=wi, word_dict=wd)
    return sorted(
        [
            e
            for e in entries
            if resolve_debut_folder_for_id(e.music_id, e.title) == folder
            and not e.content_removed
        ],
        key=lambda e: e.music_id,
    )


def _collect_existing_stems(folder: str) -> set[str]:
    dest = BRANCH_ROOT / folder
    stems: set[str] = set()
    if not dest.is_dir():
        return stems
    for p in dest.glob("*.mcz"):
        stems.add(p.stem)
        stems.add(p.stem.replace("_", "'"))
        stems.add(p.stem.replace("'", "_"))
    return stems


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


def _clear_folder_mcz(folder: str) -> int:
    dest = BRANCH_ROOT / folder
    dest.mkdir(parents=True, exist_ok=True)
    removed = 0
    for mcz in dest.glob("*.mcz"):
        mcz.unlink()
        removed += 1
    return removed


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
    return True, dest.name


def _run_folder(
    data_dir: Path,
    folder: str,
    *,
    fresh: bool,
    music_info: dict,
    word_info: dict,
    jacket_index: dict,
    report: dict,
) -> None:
    cleared = _clear_folder_mcz(folder) if fresh else 0
    targets = _load_targets(data_dir, folder)
    total = len(targets)
    existing = _collect_existing_stems(folder) if not fresh else set()
    pending = [e for e in targets if fresh or not _is_done(e.title, existing)]
    skip_count = total - len(pending)

    _safe_print(f"\n{'=' * 60}")
    _safe_print(f"[{folder}] 本地可提取 {total} 首")
    if fresh:
        _safe_print(f"  已清空旧 MCZ {cleared} 个 | 全量重跑 {len(pending)} 首")
    else:
        _safe_print(f"  跳过已有 {skip_count} 首 | 待处理 {len(pending)} 首")
    _safe_print("=" * 60)

    if not pending:
        _safe_print(f"[{folder}] 无需处理")
        report["folders"][folder] = {
            "total": total, "ok": 0, "fail": 0, "skip": skip_count, "cleared": cleared
        }
        return

    ok_count = 0
    fail_count = 0
    t0 = time.time()

    for idx, entry in enumerate(pending, start=1):
        done = ok_count + fail_count
        remain = len(pending) - done
        elapsed = time.time() - t0
        eta = (elapsed / done * remain) if done > 0 else 0.0
        pct = 100.0 * done / len(pending)

        _safe_print(
            f"\n[{folder}] {_progress_bar(done, len(pending))} {pct:5.1f}% | "
            f"{idx}/{len(pending)} | "
            f"成功 {ok_count} 失败 {fail_count} 剩余 {remain} | "
            f"用时 {_fmt_eta(elapsed)} ETA {_fmt_eta(eta)}"
        )
        _safe_print(f"  >> {entry.title} ({entry.music_id})")

        try:
            ok, detail = _process_one(
                entry,
                folder,
                music_info=music_info,
                word_info=word_info,
                jacket_index=jacket_index,
                force_extract=fresh,
            )
        except Exception as exc:
            ok, detail = False, str(exc)

        if ok:
            ok_count += 1
            _safe_print(f"    OK  {detail}")
            report["ok"].append(
                {"folder": folder, "music_id": entry.music_id, "title": entry.title, "mcz": detail}
            )
        else:
            fail_count += 1
            _safe_print(f"    FAIL  {detail}")
            report["fail"].append(
                {
                    "folder": folder,
                    "music_id": entry.music_id,
                    "title": entry.title,
                    "reason": detail,
                }
            )

    branch_n = len(list((BRANCH_ROOT / folder).glob("*.mcz")))
    report["folders"][folder] = {
        "total": total,
        "ok": ok_count,
        "fail": fail_count,
        "skip": skip_count,
        "cleared": cleared,
        "branch_total": branch_n,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    _safe_print(
        f"\n[{folder}] 完成: 成功 {ok_count}/{len(pending)} | 失败 {fail_count} | "
        f"Branch 共 {branch_n} 个 MCZ"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="jubeat-ripples / ripples-append 初版曲批量转 MCZ"
    )
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=str(DEFAULT_DATA_DIR),
        help="游戏数据目录",
    )
    parser.add_argument(
        "--folders",
        nargs="+",
        default=list(DEFAULT_FOLDERS),
        metavar="FOLDER",
        help="目标 Branch 子目录（默认 ripples + ripples-append）",
    )
    parser.add_argument(
        "--no-fresh",
        action="store_true",
        help="增量模式，不删除已有 MCZ",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    folders = list(args.folders)
    fresh = not args.no_fresh

    if not data_dir.is_dir():
        _safe_print(f"错误: 游戏数据目录不存在: {data_dir}")
        return 1

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP.mkdir(parents=True, exist_ok=True)

    _safe_print("=" * 60)
    _safe_print("jubeat-ripples / ripples-append → MCZ")
    _safe_print(f"数据目录: {data_dir}")
    _safe_print(f"输出根目录: {BRANCH_ROOT}")
    _safe_print(f"目标: {', '.join(folders)}")
    _safe_print(f"模式: {'覆盖重跑' if fresh else '增量'}")

    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    music_info = load_music_info(mp, word_dict=wd) if mp else {}
    word_info = load_word_info(wp) if wp else {}
    jacket_index = build_jacket_index(data_dir)

    report: dict = {"fresh": fresh, "folders": {}, "ok": [], "fail": []}
    t0 = time.time()

    for folder in folders:
        _run_folder(
            data_dir,
            folder,
            fresh=fresh,
            music_info=music_info,
            word_info=word_info,
            jacket_index=jacket_index,
            report=report,
        )

    report["elapsed_sec"] = round(time.time() - t0, 1)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    total_ok = len(report["ok"])
    total_fail = len(report["fail"])
    _safe_print(f"\n{'=' * 60}")
    _safe_print(f"全部完成: 成功 {total_ok} | 失败 {total_fail}")
    _safe_print(f"报告: {REPORT_PATH}")
    _safe_print("=" * 60)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
