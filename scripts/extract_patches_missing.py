#!/usr/bin/env python3
"""批量审计增量补丁并提取 Branch 缺失的 MCZ。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from core.malody_writer import convert_song, mcz_safe_filename
from core.song_catalog import find_extracted_song_dir
from core.song_database import get_reference_song_name
from core.song_debut import resolve_debut_folder_for_id
from core.unpacker import (
    build_jacket_index,
    extract_ifs,
    extract_song,
    find_metadata_xml,
    is_ifs_content_removed,
    load_music_info,
    load_word_dictionary,
    load_word_info,
)
from scripts.recover_from_legacy_data import _branch_has, _load_catalog

BEYOND = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
EXTRACT_DIR = ROOT / "debug_out" / "patches_extract"
MCZ_TEMP = ROOT / "debug_out" / "patches_mcz"

# music_id → (显示曲名, 版本目录)；用于 word_info 读音名无法映射时
KNOWN_IDS: dict[int, tuple[str, str]] = {
    11000053: ("MONOLITH", "jubeat-ave"),
    11000074: ("Magical electrica", "jubeat-beyond-ave"),
    11000078: ("IGNITE THE IRON HEART", "jubeat-beyond-ave"),
    11000082: ("AMBERGRIS [ H ]", "jubeat-ave"),
}


def _safe_print(*args) -> None:
    text = " ".join(str(a) for a in args)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), flush=True)


def _has_eve(ifs: Path) -> bool:
    d = ROOT / "debug_out" / "_eve_peek"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        names = extract_ifs(ifs, d)
        return any(n.endswith(".eve") for n in names)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _charts_ok(mcz: Path) -> bool:
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


def _resolve_title_folder(mid: int, catalog_title: str) -> tuple[str, str] | None:
    if mid in KNOWN_IDS:
        return KNOWN_IDS[mid]

    for title in (
        catalog_title,
        get_reference_song_name(mid) or "",
    ):
        if not title or title.startswith("unknown_"):
            continue
        folder = resolve_debut_folder_for_id(mid, title)
        if folder and folder != "unknown":
            return title, folder

    folder = resolve_debut_folder_for_id(mid, catalog_title)
    if folder and folder != "unknown":
        return catalog_title, folder
    return None


def _scan_patch(patch_data: Path) -> list[dict]:
    patch = _load_catalog(patch_data)
    targets: list[dict] = []
    for mid, entry in sorted(patch.items()):
        if entry.content_removed or is_ifs_content_removed(entry.ifs_path):
            continue
        if 11010000 <= mid < 11020000 and not _has_eve(entry.ifs_path):
            continue
        if not _has_eve(entry.ifs_path):
            continue

        resolved = _resolve_title_folder(mid, entry.title)
        if not resolved:
            targets.append(
                {
                    "music_id": mid,
                    "title": entry.title,
                    "folder": None,
                    "status": "no_folder",
                    "ifs_path": str(entry.ifs_path),
                }
            )
            continue

        title, folder = resolved
        if _branch_has(title, folder):
            continue
        targets.append(
            {
                "music_id": mid,
                "title": title,
                "folder": folder,
                "status": "missing",
                "ifs_path": str(entry.ifs_path),
            }
        )
    return targets


def _extract_one(
    row: dict,
    *,
    music_info: dict,
    word_info: dict,
    jacket_index: dict,
) -> tuple[bool, str]:
    mid = row["music_id"]
    title = row["title"]
    folder = row["folder"]
    ifs = Path(row["ifs_path"])

    patched = dict(music_info)
    base = patched.get(mid, {})
    patched[mid] = {**base, "name": title, "title_name": title}

    song_dir = find_extracted_song_dir(EXTRACT_DIR, mid)
    if not song_dir:
        song_dir = extract_song(
            ifs,
            patched,
            EXTRACT_DIR,
            ifs_dir=ifs.parent,
            word_info=word_info,
            jacket_index=jacket_index,
        )
    if not song_dir:
        return False, "解包失败"

    mcz = convert_song(song_dir, MCZ_TEMP, skip_existing=False)
    if not mcz or not _charts_ok(mcz):
        if mcz:
            mcz.unlink(missing_ok=True)
        return False, "转换失败"

    dest_dir = BRANCH / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / mcz.name
    shutil.copy2(mcz, dest)
    return True, str(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="批量补丁缺失曲提取")
    parser.add_argument("patch_data_dirs", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wp = find_metadata_xml(BEYOND, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(BEYOND, "music_info.xml")
    music_info = load_music_info(mp, word_dict=wd) if mp else {}
    word_info = load_word_info(wp) if wp else {}
    jacket_index = build_jacket_index(BEYOND)

    all_missing: list[dict] = []
    all_no_folder: list[dict] = []
    seen: set[int] = set()

    for raw in args.patch_data_dirs:
        patch_data = raw
        if patch_data.name != "data":
            cand = patch_data / "data"
            if cand.is_dir():
                patch_data = cand
        if not patch_data.is_dir():
            _safe_print(f"跳过（不存在）: {raw}")
            continue

        _safe_print(f"\n{'=' * 60}")
        _safe_print(f"审计: {patch_data}")
        targets = _scan_patch(patch_data)
        missing = [t for t in targets if t["status"] == "missing"]
        no_folder = [t for t in targets if t["status"] == "no_folder"]
        _safe_print(f"  待提取: {len(missing)} | 无版本映射: {len(no_folder)}")

        for t in missing:
            if t["music_id"] in seen:
                continue
            seen.add(t["music_id"])
            all_missing.append({**t, "patch": str(patch_data)})
            _safe_print(f"  MISSING {t['music_id']}\t{t['title']}\t-> {t['folder']}")

        for t in no_folder:
            if t["music_id"] not in {x["music_id"] for x in all_no_folder}:
                all_no_folder.append({**t, "patch": str(patch_data)})
                _safe_print(f"  NO_MAP  {t['music_id']}\t{t['title']}")

    report = {
        "missing": all_missing,
        "no_folder": all_no_folder,
    }
    out = ROOT / "debug_out" / "patches_missing_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n汇总: 待提取 {len(all_missing)} | 无映射 {len(all_no_folder)}")
    _safe_print(f"报告: {out}")

    if args.dry_run or not all_missing:
        return 0 if not all_no_folder else 1

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP.mkdir(parents=True, exist_ok=True)
    ok, fail = 0, 0
    for row in all_missing:
        _safe_print(f"\n提取 {row['title']} ({row['music_id']}) ...")
        try:
            success, detail = _extract_one(
                row, music_info=music_info, word_info=word_info, jacket_index=jacket_index
            )
        except Exception as exc:
            success, detail = False, str(exc)
        if success:
            ok += 1
            _safe_print(f"  OK {detail}")
        else:
            fail += 1
            _safe_print(f"  FAIL {detail}")

    _safe_print(f"\n完成: 成功 {ok} | 失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
