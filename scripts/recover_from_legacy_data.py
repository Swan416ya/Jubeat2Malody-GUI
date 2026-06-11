#!/usr/bin/env python3
"""从旧版街机数据恢复 Beyond Ave 已删/不可用的曲目到 Branch。

用法:
  python -u scripts/recover_from_legacy_data.py
  python -u scripts/recover_from_legacy_data.py --dry-run
  python -u scripts/recover_from_legacy_data.py --source "E:\\...\\Festo\\...\\contents\\data"
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
from core.unpacker import (
    build_jacket_index,
    extract_song,
    find_metadata_xml,
    is_ifs_content_removed,
    load_music_info,
    load_word_dictionary,
    load_word_info,
)

DEFAULT_SOURCE = Path(r"E:\Program Files (x86)\Jubeat Festo\L44-011-2022052400\contents\data")
DEFAULT_CURRENT = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
EXTRACT_DIR = ROOT / "debug_out" / "legacy_recover_extract"
MCZ_TEMP = ROOT / "debug_out" / "legacy_recover_mcz"
REPORT = ROOT / "debug_out" / "legacy_recover_report.json"


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


def _load_catalog(data_dir: Path) -> dict[int, object]:
    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    mi = load_music_info(mp, word_dict=wd) if mp else {}
    wi = load_word_info(wp) if wp else {}
    entries = scan_game_catalog(data_dir, None, music_info=mi, word_info=wi, word_dict=wd)
    return {e.music_id: e for e in entries}


def _branch_has(title: str, folder: str) -> bool:
    dest = BRANCH / folder
    if not dest.is_dir():
        return False
    safe = mcz_safe_filename(title)
    for stem in (title, safe, title.replace("'", "_")):
        if (dest / f"{stem}.mcz").exists():
            return True
        if " [ 2 ]" in title or title.endswith("[ 2 ]"):
            alt = mcz_safe_filename(title)
            if (dest / f"{alt}.mcz").exists():
                return True
    return any(p.stem == safe or p.stem == title for p in dest.glob("*.mcz"))


def _find_recoverable(source_dir: Path, current_dir: Path) -> list[dict]:
    src = _load_catalog(source_dir)
    cur = _load_catalog(current_dir) if current_dir.is_dir() else {}

    targets: list[dict] = []
    for mid, entry in src.items():
        if entry.content_removed:
            continue
        folder = resolve_debut_folder_for_id(mid, entry.title)
        if not folder or folder == "unknown":
            continue

        cur_e = cur.get(mid)
        reason = None
        if cur_e is None:
            reason = "当前版无数据"
        elif cur_e.content_removed:
            reason = "当前版版权到期"
        else:
            continue

        if _branch_has(entry.title, folder):
            continue

        targets.append(
            {
                "music_id": mid,
                "title": entry.title,
                "folder": folder,
                "reason": reason,
                "ifs_path": str(entry.ifs_path),
            }
        )
    return sorted(targets, key=lambda x: (x["folder"], x["music_id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="从旧版数据恢复已删曲目")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_data = args.source
    if source_data.name != "data":
        candidate = source_data / "data"
        if candidate.is_dir():
            source_data = candidate

    if not source_data.is_dir():
        _safe_print(f"错误: 源数据目录不存在: {source_data}")
        return 1

    _safe_print("扫描可恢复曲目 ...")
    _safe_print(f"  源数据: {source_data}")
    _safe_print(f"  当前版: {args.current}")
    targets = _find_recoverable(source_data, args.current)

    by_folder: dict[str, int] = {}
    for t in targets:
        by_folder[t["folder"]] = by_folder.get(t["folder"], 0) + 1

    _safe_print(f"\n可恢复 {len(targets)} 首:")
    for folder, n in sorted(by_folder.items()):
        _safe_print(f"  {folder}: {n}")
    for t in targets[:30]:
        _safe_print(f"  [{t['reason']}] {t['music_id']} {t['title']} -> {t['folder']}")
    if len(targets) > 30:
        _safe_print(f"  ... 还有 {len(targets) - 30} 首")

    if args.dry_run:
        REPORT.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")
        _safe_print(f"\n[dry-run] 报告: {REPORT}")
        return 0

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP.mkdir(parents=True, exist_ok=True)

    wp = find_metadata_xml(source_data, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(source_data, "music_info.xml")
    music_info = load_music_info(mp, word_dict=wd) if mp else {}
    word_info = load_word_info(wp) if wp else {}
    jacket_index = build_jacket_index(source_data)

    ok, fail = 0, 0
    results: dict = {"ok": [], "fail": []}
    t0 = time.time()

    for i, t in enumerate(targets, 1):
        mid = t["music_id"]
        title = t["title"]
        folder = t["folder"]
        _safe_print(f"\n[{i}/{len(targets)}] {title} ({mid}) -> {folder}")
        _safe_print(f"  原因: {t['reason']}")

        ifs_path = Path(t["ifs_path"])
        if is_ifs_content_removed(ifs_path):
            _safe_print("  SKIP: 源数据亦为占位")
            fail += 1
            results["fail"].append({**t, "error": "源占位"})
            continue

        song_dir = find_extracted_song_dir(EXTRACT_DIR, mid)
        if not song_dir:
            _safe_print("  解包...")
            song_dir = extract_song(
                ifs_path,
                music_info,
                EXTRACT_DIR,
                ifs_dir=ifs_path.parent,
                word_info=word_info,
                jacket_index=jacket_index,
            )
        if not song_dir:
            _safe_print("  FAIL: 解包失败")
            fail += 1
            results["fail"].append({**t, "error": "解包失败"})
            continue

        _safe_print("  转换 MCZ...")
        mcz = convert_song(song_dir, MCZ_TEMP, skip_existing=False)
        if not mcz or not _charts_distinct(mcz):
            if mcz:
                mcz.unlink(missing_ok=True)
            _safe_print("  FAIL: 转换失败")
            fail += 1
            results["fail"].append({**t, "error": "转换失败"})
            continue

        dest_dir = BRANCH / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / mcz.name
        shutil.copy2(mcz, dest)
        ok += 1
        _safe_print(f"  OK -> {dest}")
        results["ok"].append({**t, "mcz": str(dest)})

    results["summary"] = {
        "total": len(targets),
        "ok": ok,
        "fail": fail,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n完成: 成功 {ok} | 失败 {fail} | 报告 {REPORT}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
