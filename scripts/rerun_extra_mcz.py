"""补跑：合并多个 extract 目录，跳过已处理的 music_id，补全缺失版本。

beyond_ave_extract (720首) 已跑完，但 jubeat-ave / jubeat-ripples /
jubeat-festo 等版本的历史曲在其他 extract 目录里。本脚本合并所有 extract
目录、按 music_id 去重、跳过已跑过的，补跑剩余。

用 --start/--limit 分段，与 rerun_all_mcz_from_extract.py 一致。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # 为了 import scripts.*

from core.malody_writer import convert_song
from core.song_debut import resolve_debut_folder_for_id
from core.song_pack import detect_song_source
from scripts.rerun_all_mcz_from_extract import (
    _parse_music_id, _resolve_title_from_info, _charts_distinct, _safe_print
)

EXTRACT_DIRS = [
    ROOT / "debug_out" / "beyond_ave_extract",
    ROOT / "debug_out" / "arcade_rerun_extract",
    ROOT / "debug_out" / "ripples_extract",
    ROOT / "debug_out" / "arcade_release_extract",
    ROOT / "debug_out" / "festo_extract",
]
DEFAULT_BRANCH_ROOT = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
MCZ_TEMP = ROOT / "debug_out" / "_rerun_mcz_temp"
REPORT_PATH = ROOT / "debug_out" / "rerun_extra_mcz_report.json"


def _collect_merged() -> list[tuple[int, Path]]:
    """合并所有 extract 目录，按 music_id 去重，返回按 mid 排序的 (mid, song_dir) 列表。"""
    seen: dict[int, Path] = {}
    for extract_dir in EXTRACT_DIRS:
        if not extract_dir.is_dir():
            continue
        for d in extract_dir.iterdir():
            if not d.is_dir():
                continue
            mid = _parse_music_id(d.name)
            if mid <= 0:
                continue
            if not (d / "song_info.txt").is_file():
                continue
            if mid not in seen:
                seen[mid] = d
    return sorted(seen.items(), key=lambda x: x[0])


def _already_done_mids(branch_root: Path) -> set[int]:
    """收集 Branch 里已生成的 .mcz 对应的 music_id（从同名 song_info 反查不到，用 mcz stem 近似）。

    实际上更可靠的做法：扫描 beyond_ave_extract 已跑的 report。但简单起见，
    直接看 Branch 现有 .mcz 的 stem，匹配 extract 目录里的 mid。
    """
    done = set()
    if not branch_root.is_dir():
        return done
    # 扫所有 extract 目录，建立 mid -> song_dir 名映射，再对照 Branch mcz stem
    mid_to_stem = {}
    for extract_dir in EXTRACT_DIRS:
        if not extract_dir.is_dir():
            continue
        for d in extract_dir.iterdir():
            if not d.is_dir():
                continue
            mid = _parse_music_id(d.name)
            if mid > 0:
                mid_to_stem[mid] = d.name
    # 反向：mcz stem -> mid
    stem_to_mid = {}
    for mid, name in mid_to_stem.items():
        # extract 目录名格式 {mid}_{title}，mcz stem 通常是 {title} 或 {safe_title}
        title_part = name.split("_", 1)[1] if "_" in name else name
        stem_to_mid[title_part] = mid
        stem_to_mid[title_part.replace("_", "'")] = mid
        stem_to_mid[title_part.replace("'", "_")] = mid

    for mcz in branch_root.rglob("*.mcz"):
        stem = mcz.stem
        if stem in stem_to_mid:
            done.add(stem_to_mid[stem])
    return done


def process_song(song_dir: Path, branch_root: Path) -> tuple[bool, str, str]:
    mid = _parse_music_id(song_dir.name)
    title = _resolve_title_from_info(song_dir)
    folder = resolve_debut_folder_for_id(mid, title)
    if not folder:
        return False, "", "未知初出版本"

    source = detect_song_source(song_dir)
    if source == "unknown":
        return False, folder, "未知谱面源"

    mcz = convert_song(song_dir, MCZ_TEMP, skip_existing=False)
    if not mcz or not mcz.is_file():
        return False, folder, "convert_song 返回空"
    if not _charts_distinct(mcz):
        mcz.unlink(missing_ok=True)
        return False, folder, "谱面异常或为空"

    dest_dir = branch_root / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / mcz.name
    shutil.copy2(mcz, dest)
    mcz.unlink(missing_ok=True)
    return True, folder, str(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="补跑其他 extract 目录的缺失曲")
    parser.add_argument("--branch-root", default=str(DEFAULT_BRANCH_ROOT))
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="0=全部")
    args = parser.parse_args()

    branch_root = Path(args.branch_root)
    if not branch_root.is_dir():
        _safe_print(f"错误: Branch 目录不存在: {branch_root}")
        return 1

    MCZ_TEMP.mkdir(parents=True, exist_ok=True)

    merged = _collect_merged()
    done = _already_done_mids(branch_root)
    pending = [(mid, d) for mid, d in merged if mid not in done]
    _safe_print(f"合并总曲数: {len(merged)}, 已完成: {len(done)}, 待补跑: {len(pending)}")

    start = max(0, min(args.start, len(pending)))
    if args.limit > 0:
        batch = pending[start:start + args.limit]
    else:
        batch = pending[start:]
    end = start + len(batch)
    _safe_print(f"本段处理: {len(batch)} 首 (偏移 {start}..{end} / 待补跑 {len(pending)})")
    _safe_print("=" * 60)

    report = {"total_pending": len(pending), "ok": [], "fail": [], "folder_stats": {}}
    t0 = time.time()
    for i, (mid, song_dir) in enumerate(batch, 1):
        title = _resolve_title_from_info(song_dir)
        elapsed = time.time() - t0
        eta = (elapsed / i) * (len(batch) - i) if i > 0 else 0
        _safe_print(f"[{i}/{len(batch)}] {mid} {title}  (已用 {elapsed:.0f}s, 剩余 ~{eta:.0f}s)")
        try:
            ok, folder, info = process_song(song_dir, branch_root)
        except Exception as exc:
            ok, folder, info = False, "", f"异常: {exc}"
        if ok:
            report["ok"].append({"music_id": mid, "title": title, "folder": folder, "mcz": info})
            report["folder_stats"][folder] = report["folder_stats"].get(folder, 0) + 1
            _safe_print(f"  OK -> {folder}/{Path(info).name}")
        else:
            report["fail"].append({"music_id": mid, "title": title, "folder": folder, "reason": info})
            _safe_print(f"  FAIL: {info}")

    report["elapsed_sec"] = round(time.time() - t0, 1)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n完成: 成功 {len(report['ok'])} | 失败 {len(report['fail'])} | 耗时 {report['elapsed_sec']}s")
    for f, c in sorted(report["folder_stats"].items()):
        _safe_print(f"  {f}: {c}")
    if report["fail"]:
        _safe_print("失败:")
        for f in report["fail"][:20]:
            _safe_print(f"  {f['music_id']} {f['title']}: {f['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
