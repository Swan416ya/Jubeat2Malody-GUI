#!/usr/bin/env python3
"""jubeat-festo 初版曲批量解包转 MCZ，终端实时显示进度。

用法:
  python -u scripts/batch_festo_mcz.py
  python -u scripts/batch_festo_mcz.py --fresh          # 清空 jubeat-festo/ 后全量重跑
  python -u scripts/batch_festo_mcz.py "D:/jubeat/data" # 指定游戏数据目录
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

TARGET_FOLDER = "jubeat-festo"
DEFAULT_DATA_DIR = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH_ROOT = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
EXTRACT_DIR = ROOT / "debug_out" / "festo_extract"
MCZ_TEMP = ROOT / "debug_out" / "festo_mcz"
REPORT_PATH = ROOT / "debug_out" / "festo_mcz_report.json"


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


def _load_catalog(data_dir: Path) -> list:
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
            if resolve_debut_folder_for_id(e.music_id, e.title) == TARGET_FOLDER
            and not e.content_removed
        ],
        key=lambda e: e.music_id,
    )


def _collect_existing_stems() -> set[str]:
    dest = BRANCH_ROOT / TARGET_FOLDER
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


def _process_one(
    entry,
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

    _safe_print(f"    转换 MCZ ...")
    mcz = convert_song(song_dir, MCZ_TEMP, skip_existing=False)
    if not mcz or not _charts_distinct(mcz):
        if mcz:
            mcz.unlink(missing_ok=True)
        return False, "转换失败或谱面异常"

    dest_dir = BRANCH_ROOT / TARGET_FOLDER
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / mcz.name
    shutil.copy2(mcz, dest)
    return True, dest.name


def main() -> int:
    parser = argparse.ArgumentParser(description="jubeat-festo 初版曲批量转 MCZ")
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=str(DEFAULT_DATA_DIR),
        help="游戏数据目录 (默认 Beyond Ave contents/data)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="清空 Branch/jubeat-festo/ 后全量重跑",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        _safe_print(f"错误: 游戏数据目录不存在: {data_dir}")
        return 1

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP.mkdir(parents=True, exist_ok=True)
    dest_dir = BRANCH_ROOT / TARGET_FOLDER
    dest_dir.mkdir(parents=True, exist_ok=True)

    cleared = 0
    if args.fresh:
        for mcz in dest_dir.glob("*.mcz"):
            mcz.unlink()
            cleared += 1

    _safe_print("=" * 60)
    _safe_print("jubeat-festo 初版曲 → MCZ")
    _safe_print(f"数据目录: {data_dir}")
    _safe_print(f"输出目录: {dest_dir}")
    if args.fresh:
        _safe_print(f"模式: 全量重跑（已清空 {cleared} 个旧 MCZ）")
    else:
        _safe_print("模式: 增量（跳过 Branch 已有 MCZ）")
    _safe_print("扫描曲库 ...")

    targets = _load_catalog(data_dir)
    total = len(targets)
    existing = _collect_existing_stems()

    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    music_info = load_music_info(mp, word_dict=wd) if mp else {}
    word_info = load_word_info(wp) if wp else {}
    jacket_index = build_jacket_index(data_dir)

    pending = [e for e in targets if args.fresh or not _is_done(e.title, existing)]
    skip_count = total - len(pending)

    _safe_print(f"本地可提取: {total} 首 | 已有跳过: {skip_count} 首 | 待处理: {len(pending)} 首")
    _safe_print("=" * 60)

    if not pending:
        _safe_print("无需处理，已全部完成。")
        return 0

    ok_count = 0
    fail_count = 0
    t0 = time.time()
    report: dict = {
        "folder": TARGET_FOLDER,
        "total": total,
        "pending": len(pending),
        "skipped_existing": skip_count,
        "fresh": args.fresh,
        "ok": [],
        "fail": [],
    }

    for idx, entry in enumerate(pending, start=1):
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
        _safe_print(f"  >> {entry.title} ({entry.music_id})")

        try:
            ok, detail = _process_one(
                entry,
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
                {"music_id": entry.music_id, "title": entry.title, "mcz": detail}
            )
        else:
            fail_count += 1
            _safe_print(f"    FAIL  {detail}")
            report["fail"].append(
                {
                    "music_id": entry.music_id,
                    "title": entry.title,
                    "reason": detail,
                }
            )

    elapsed = time.time() - t0
    branch_count = len(list(dest_dir.glob("*.mcz")))
    report["branch_total"] = branch_count
    report["elapsed_sec"] = round(elapsed, 1)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _safe_print("\n" + "=" * 60)
    _safe_print(
        f"完成: 本次成功 {ok_count}/{len(pending)} | 失败 {fail_count} | "
        f"跳过 {skip_count} | Branch 共 {branch_count} 个 MCZ"
    )
    _safe_print(f"耗时 {elapsed / 60:.1f} 分钟 | 报告: {REPORT_PATH}")
    _safe_print("=" * 60)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
