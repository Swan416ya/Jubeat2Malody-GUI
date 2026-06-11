#!/usr/bin/env python3
"""街机谱面批量发布：按 atwiki 初出版本归类 + 提取指定版本初版曲转 MCZ。

用法:
  python scripts/batch_arcade_release.py [游戏数据目录] [目标版本文件夹]

示例:
  python scripts/batch_arcade_release.py                    # jubeat-beyond-ave
  python scripts/batch_arcade_release.py "" jubeat-ave    # jubeat Ave
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.malody_writer import convert_song, mcz_safe_filename
from core.song_catalog import find_extracted_song_dir, scan_game_catalog
from core.song_debut import resolve_debut_folder, resolve_debut_folder_for_id
from core.song_pack import detect_song_source
from core.unpacker import extract_song, load_music_info, load_word_dictionary, find_metadata_xml

DEFAULT_DATA_DIR = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
BRANCH_ROOT = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")
EXTRACT_DIR = ROOT / "debug_out" / "arcade_release_extract"
MCZ_TEMP = ROOT / "debug_out" / "arcade_release_mcz"
REPORT_PATH = ROOT / "debug_out" / "arcade_release_report.json"

EXTRA_FOLDERS = (
    "jubeat-saucer",
    "jubeat-saucer-fulfill",
    "jubeat-prop",
    "jubeat-qubell",
)


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
        return len(sigs) > 1 or len(sigs) == 1


def _ensure_folders() -> None:
    BRANCH_ROOT.mkdir(parents=True, exist_ok=True)
    for name in EXTRA_FOLDERS:
        (BRANCH_ROOT / name).mkdir(parents=True, exist_ok=True)


def _find_extracted(mid: int) -> Path | None:
    for base in (EXTRACT_DIR, ROOT / "debug_out"):
        found = find_extracted_song_dir(base, mid)
        if found:
            return found
    return None


def _reclassify_existing_mcz(report: dict) -> None:
    """将 Branch 内放错版本的 MCZ 移到正确目录。"""
    moves: list[dict] = []
    mcz_files = [
        p for p in BRANCH_ROOT.rglob("*.mcz") if "音乐魔方" not in p.parts
    ]
    for mcz in sorted(mcz_files):
        title = mcz.stem
        folder = resolve_debut_folder(title)
        if not folder:
            continue
        dest_dir = BRANCH_ROOT / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / mcz.name
        if dest.resolve() == mcz.resolve():
            continue
        if dest.exists():
            mcz.unlink()
            moves.append({"title": title, "from": str(mcz.parent.name), "to": folder, "action": "removed duplicate"})
        else:
            shutil.move(str(mcz), str(dest))
            moves.append({"title": title, "from": str(mcz.parent.name), "to": folder, "action": "moved"})
    report["reclassified"] = moves


def _load_catalog(data_dir: Path) -> list:
    word_path = find_metadata_xml(data_dir, "word_info.xml")
    word_dict = load_word_dictionary(word_path) if word_path else {}
    music_path = find_metadata_xml(data_dir, "music_info.xml")
    music_info = load_music_info(music_path, word_dict=word_dict) if music_path else {}
    word_info_path = find_metadata_xml(data_dir, "word_info.xml")
    from core.unpacker import load_word_info

    word_info = load_word_info(word_info_path) if word_info_path else {}
    return scan_game_catalog(
        data_dir,
        EXTRACT_DIR,
        music_info=music_info,
        word_info=word_info,
        word_dict=word_dict,
    )


def _convert_to_branch(song_dir: Path, title: str, music_id: int, report: dict) -> None:
    folder = resolve_debut_folder_for_id(music_id, title) or "unknown"
    if folder == "unknown":
        report["failed"].append({"music_id": music_id, "title": title, "reason": "未知初出版本"})
        return

    mcz = convert_song(song_dir, MCZ_TEMP, skip_existing=False)
    if not mcz or not _charts_distinct(mcz):
        if mcz:
            mcz.unlink(missing_ok=True)
        report["failed"].append({"music_id": music_id, "title": title, "reason": "转换失败或谱面相同"})
        return

    dest_dir = BRANCH_ROOT / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / mcz.name
    shutil.copy2(mcz, dest)
    report["converted"].append(
        {"music_id": music_id, "title": title, "folder": folder, "mcz": str(dest)}
    )
    _safe_print(f"OK [{folder}] {title}")


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    target_folder = "jubeat-beyond-ave"
    data_dir = DEFAULT_DATA_DIR
    if args:
        p = Path(args[0])
        if p.is_dir():
            data_dir = p
            if len(args) > 1:
                target_folder = args[1]
        else:
            target_folder = args[0]
    if not data_dir.is_dir():
        _safe_print(f"游戏数据目录不存在: {data_dir}")
        return 1

    _ensure_folders()
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP.mkdir(parents=True, exist_ok=True)

    report_path = ROOT / "debug_out" / f"release_{target_folder.replace('-', '_')}_report.json"

    report: dict = {
        "data_dir": str(data_dir),
        "target_folder": target_folder,
        "reclassified": [],
        "converted": [],
        "skipped_existing": [],
        "failed": [],
    }

    _safe_print("=== 1. 重新归类 Branch 内已有 MCZ ===")
    _reclassify_existing_mcz(report)
    for item in report["reclassified"]:
        _safe_print(f"  {item['action']}: {item['title']} -> {item['to']}")

    _safe_print(f"\n=== 2. 扫描曲库，提取 {target_folder} 初版曲 ===")
    entries = _load_catalog(data_dir)
    targets = []
    for entry in entries:
        folder = resolve_debut_folder_for_id(entry.music_id, entry.title)
        if folder != target_folder:
            continue
        if entry.content_removed:
            report["failed"].append(
                {"music_id": entry.music_id, "title": entry.title, "reason": "版权到期"}
            )
            continue
        targets.append(entry)

    _safe_print(f"{target_folder} 初版曲（本地有数据）: {len(targets)} 首")

    existing_mcz: set[str] = set()
    for p in BRANCH_ROOT.rglob("*.mcz"):
        existing_mcz.add(p.stem)
        existing_mcz.add(p.stem.replace("_", "'"))
        existing_mcz.add(p.stem.replace("'", "_"))

    for entry in targets:
        title = entry.title
        mid = entry.music_id
        if (
            title in existing_mcz
            or mcz_safe_filename(title) in existing_mcz
            or str(mid) in existing_mcz
        ):
            report["skipped_existing"].append({"music_id": mid, "title": title})
            continue

        song_dir = entry.extracted_dir or _find_extracted(mid)
        if song_dir and (song_dir / "song_info.txt").is_file():
            if detect_song_source(song_dir) != "arcade":
                song_dir = None

        if not song_dir:
            _safe_print(f"提取 {title} ({mid})...")
            try:
                word_path = find_metadata_xml(data_dir, "word_info.xml")
                word_dict = load_word_dictionary(word_path) if word_path else {}
                music_path = find_metadata_xml(data_dir, "music_info.xml")
                music_info = load_music_info(music_path, word_dict=word_dict) if music_path else {}
                from core.unpacker import load_word_info, build_jacket_index

                word_info = load_word_info(word_path) if word_path else {}
                jacket_index = build_jacket_index(data_dir)
                song_dir = extract_song(
                    entry.ifs_path,
                    music_info,
                    EXTRACT_DIR,
                    ifs_dir=entry.ifs_path.parent,
                    word_info=word_info,
                    jacket_index=jacket_index,
                )
            except Exception as exc:
                report["failed"].append(
                    {"music_id": mid, "title": title, "reason": f"解包异常: {exc}"}
                )
                continue

        if not song_dir:
            report["failed"].append({"music_id": mid, "title": title, "reason": "解包失败"})
            continue

        _convert_to_branch(song_dir, title, mid, report)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _safe_print(
        f"\n完成: 归类 {len(report['reclassified'])} | "
        f"新转 {len(report['converted'])} | "
        f"跳过 {len(report['skipped_existing'])} | "
        f"失败 {len(report['failed'])}"
    )
    _safe_print(f"报告: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
