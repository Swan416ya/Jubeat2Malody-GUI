"""轻量全量重跑：直接遍历已解包目录，绕过 scan_game_catalog 的全量扫描。

issue #1 修复后，需要把 Branch 工作树的所有 .mcz 用新代码重新生成一遍。
原 batch_beyond_ave_mcz.py 在 scan_game_catalog 阶段会 rglob 12G 数据目录
找 xml/ifs，单次扫描超 10 分钟。本脚本直接遍历 debug_out/beyond_ave_extract/
下 720 个已解包目录，对每个调 convert_song 生成 .mcz 并覆盖到 Branch。

用法：
    python scripts/rerun_all_mcz_from_extract.py [--extract-dir DIR] [--branch-root DIR]

默认：
    --extract-dir  debug_out/beyond_ave_extract
    --branch-root  E:\\Program Files (x86)\\Jubeat BeyondAve\\Branch
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.malody_writer import convert_song
from core.song_debut import resolve_debut_folder_for_id
from core.song_pack import detect_song_source

DEFAULT_EXTRACT_DIR = ROOT / "debug_out" / "beyond_ave_extract"
DEFAULT_BRANCH_ROOT = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
MCZ_TEMP = ROOT / "debug_out" / "_rerun_mcz_temp"
REPORT_PATH = ROOT / "debug_out" / "rerun_all_mcz_report.json"

# 解包目录名格式：{music_id}_{title}
DIR_NAME_RE = re.compile(r"^(\d+)_")


def _safe_print(*args, **kwargs) -> None:
    msg = " ".join(str(a) for a in args)
    print(msg, flush=True, **kwargs)


def _charts_distinct(mcz: Path) -> bool:
    """检查 .mcz 内至少有一个合法 .mc 文件。"""
    try:
        with zipfile.ZipFile(mcz) as zf:
            for name in zf.namelist():
                if name.endswith(".mc"):
                    return True
        return False
    except (zipfile.BadZipFile, OSError):
        return False


def _parse_music_id(dir_name: str) -> int:
    m = DIR_NAME_RE.match(dir_name)
    return int(m.group(1)) if m else 0


def _resolve_title_from_info(song_dir: Path) -> str:
    """从 song_info.txt 读曲名，失败则用目录名。"""
    info_path = song_dir / "song_info.txt"
    if not info_path.is_file():
        return song_dir.name
    try:
        text = info_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("Name:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return song_dir.name


def _clear_branch_mcz(branch_root: Path) -> int:
    """清空 Branch 下所有版本文件夹的 .mcz（保留 README 和目录结构）。"""
    removed = 0
    if not branch_root.is_dir():
        return 0
    for mcz in branch_root.rglob("*.mcz"):
        try:
            mcz.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def process_song(song_dir: Path, branch_root: Path, folder_override: str | None = None) -> tuple[bool, str, str]:
    """转一首歌，返回 (ok, folder, dest_path 或 reason)。"""
    mid = _parse_music_id(song_dir.name)
    title = _resolve_title_from_info(song_dir)

    folder = folder_override or resolve_debut_folder_for_id(mid, title)
    if not folder:
        return False, "", "未知初出版本"

    # detect_song_source 验证是 arcade 谱面（避免误把 cn 目录当 arcade 转）
    source = detect_song_source(song_dir)
    if source == "unknown":
        return False, folder, f"未知谱面源"

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
    mcz.unlink(missing_ok=True)  # 清理临时文件
    return True, folder, str(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="从已解包目录全量重跑 .mcz")
    parser.add_argument("--extract-dir", default=str(DEFAULT_EXTRACT_DIR),
                        help=f"已解包目录 (默认 {DEFAULT_EXTRACT_DIR})")
    parser.add_argument("--branch-root", default=str(DEFAULT_BRANCH_ROOT),
                        help=f"Branch 工作树根目录 (默认 {DEFAULT_BRANCH_ROOT})")
    parser.add_argument("--limit", type=int, default=0,
                        help="只处理 N 首（用于预演或分段，0=全部）")
    parser.add_argument("--start", type=int, default=0,
                        help="从第 start 首（0-based 偏移）开始处理，用于分段续跑")
    parser.add_argument("--no-clear", action="store_true",
                        help="不清空 Branch 旧 .mcz（默认会先清空；分段跑时除首段外都要加）")
    args = parser.parse_args()

    extract_dir = Path(args.extract_dir)
    branch_root = Path(args.branch_root)

    if not extract_dir.is_dir():
        _safe_print(f"错误: 解包目录不存在: {extract_dir}")
        return 1
    if not branch_root.is_dir():
        _safe_print(f"错误: Branch 目录不存在: {branch_root}")
        return 1

    MCZ_TEMP.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 收集所有解包目录
    all_song_dirs = sorted(
        [d for d in extract_dir.iterdir()
         if d.is_dir() and _parse_music_id(d.name) > 0
         and (d / "song_info.txt").is_file()],
        key=lambda d: _parse_music_id(d.name)
    )
    total = len(all_song_dirs)
    start = max(0, min(args.start, total))
    if args.limit > 0:
        song_dirs = all_song_dirs[start:start + args.limit]
    else:
        song_dirs = all_song_dirs[start:]
    end = start + len(song_dirs)

    _safe_print("=" * 60)
    _safe_print("从已解包目录全量重跑 .mcz (issue #1 24 分修复)")
    _safe_print(f"解包目录: {extract_dir}")
    _safe_print(f"Branch 根: {branch_root}")
    _safe_print(f"待处理: {len(song_dirs)} 首 (偏移 {start}..{end} / 总 {total})")
    if not args.no_clear:
        _safe_print("即将清空 Branch 下所有 .mcz ...")
        cleared = _clear_branch_mcz(branch_root)
        _safe_print(f"已清空 {cleared} 个旧 .mcz")
    _safe_print("=" * 60)

    report = {
        "extract_dir": str(extract_dir),
        "branch_root": str(branch_root),
        "total": len(song_dirs),
        "ok": [],
        "fail": [],
        "folder_stats": {},
    }

    t_start = time.time()
    for i, song_dir in enumerate(song_dirs, 1):
        mid = _parse_music_id(song_dir.name)
        title = _resolve_title_from_info(song_dir)
        elapsed = time.time() - t_start
        eta = (elapsed / i) * (len(song_dirs) - i) if i > 0 else 0
        _safe_print(f"[{i}/{len(song_dirs)}] {mid} {title}  (已用 {elapsed:.0f}s, 剩余 ~{eta:.0f}s)")

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

    report["elapsed_sec"] = round(time.time() - t_start, 1)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _safe_print("=" * 60)
    _safe_print(f"完成: 成功 {len(report['ok'])} | 失败 {len(report['fail'])} | 耗时 {report['elapsed_sec']}s")
    _safe_print("各版本文件夹产出:")
    for folder, cnt in sorted(report["folder_stats"].items()):
        _safe_print(f"  {folder}: {cnt}")
    if report["fail"]:
        _safe_print("失败列表:")
        for f in report["fail"][:20]:
            _safe_print(f"  {f['music_id']} {f['title']}: {f['reason']}")
    _safe_print(f"报告: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
