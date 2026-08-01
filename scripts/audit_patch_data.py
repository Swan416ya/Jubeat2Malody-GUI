#!/usr/bin/env python3
"""审计街机增量补丁包：相对 Beyond Ave / Branch 的覆盖与缺失。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from core.malody_writer import mcz_safe_filename
from core.song_debut import resolve_debut_folder_for_id
from core.unpacker import is_ifs_content_removed
from scripts.recover_from_legacy_data import _branch_has, _load_catalog

DEFAULT_BEYOND = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
DEFAULT_BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")


def _safe_print(*args) -> None:
    text = " ".join(str(a) for a in args)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), flush=True)


def _file_hash(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_ifs(root: Path, mid: int) -> Path | None:
    hits = list(root.rglob(f"{mid}_msc.ifs"))
    return hits[0] if hits else None


def _peek_ifs(mid: int, ifs: Path) -> dict:
    from core.unpacker import extract_ifs

    d = ROOT / "debug_out" / f"patch_peek_{mid}"
    if d.exists():
        import shutil

        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    names = extract_ifs(ifs, d)
    has_eve = any(n.endswith(".eve") for n in names)
    has_bgm = any("bgm" in n.lower() for n in names)
    return {"has_eve": has_eve, "has_bgm": has_bgm, "files": sorted(names)}


def main() -> int:
    parser = argparse.ArgumentParser(description="审计增量补丁包")
    parser.add_argument("patch_data", type=Path, help="补丁 data 目录")
    parser.add_argument("--beyond", type=Path, default=DEFAULT_BEYOND)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    patch_data = args.patch_data
    if patch_data.name != "data":
        cand = patch_data / "data"
        if cand.is_dir():
            patch_data = cand

    if not patch_data.is_dir():
        _safe_print(f"错误: 目录不存在 {patch_data}")
        return 1

    report_path = args.report or (ROOT / "debug_out" / f"patch_audit_{patch_data.parent.name[:40]}.json")

    _safe_print(f"补丁: {patch_data}")
    _safe_print("扫描补丁曲库 ...")
    patch = _load_catalog(patch_data)
    _safe_print("扫描 Beyond Ave 曲库 ...")
    beyond = _load_catalog(args.beyond) if args.beyond.is_dir() else {}

    patch_ifs = {int(p.name.split("_")[0]): p for p in patch_data.rglob("*_msc.ifs")}

    in_branch: list[dict] = []
    missing_branch: list[dict] = []
    no_folder: list[dict] = []
    removed: list[dict] = []
    hold_audio_only: list[dict] = []
    not_in_beyond: list[dict] = []
    hash_diff: list[dict] = []

    for mid in sorted(patch_ifs):
        ifs = patch_ifs[mid]
        entry = patch.get(mid)
        title = entry.title if entry else f"unknown_{mid}"
        content_removed = entry.content_removed if entry else is_ifs_content_removed(ifs)

        if content_removed:
            removed.append({"music_id": mid, "title": title})
            continue

        beyond_ifs = _find_ifs(args.beyond, mid) if args.beyond.is_dir() else None
        if beyond_ifs is None:
            not_in_beyond.append({"music_id": mid, "title": title})
        elif _file_hash(ifs) != _file_hash(beyond_ifs):
            hash_diff.append({"music_id": mid, "title": title})

        folder = resolve_debut_folder_for_id(mid, title)
        if not folder or folder == "unknown":
            no_folder.append({"music_id": mid, "title": title})
            continue

        row = {"music_id": mid, "title": title, "folder": folder}
        if _branch_has(title, folder):
            in_branch.append(row)
        else:
            missing_branch.append(row)

    # Hold 谱：11010xxx 且仅 bgm
    for mid in sorted(patch_ifs):
        if not (11010000 <= mid < 11020000):
            continue
        ifs = patch_ifs[mid]
        if is_ifs_content_removed(ifs):
            continue
        peek = _peek_ifs(mid, ifs)
        if peek["has_bgm"] and not peek["has_eve"]:
            base_mid = mid - 10000
            base_e = beyond.get(base_mid) or patch.get(base_mid)
            hold_audio_only.append(
                {
                    "music_id": mid,
                    "title": (patch.get(mid).title if patch.get(mid) else f"unknown_{mid}"),
                    "base_id": base_mid,
                    "base_title": base_e.title if base_e else f"unknown_{base_mid}",
                    "files": peek["files"],
                }
            )

    _safe_print()
    _safe_print(f"补丁 IFS 总数: {len(patch_ifs)}")
    _safe_print(f"  版权占位: {len(removed)}")
    _safe_print(f"  本地 BYD 无此 IFS: {len(not_in_beyond)}")
    _safe_print(f"  与 BYD 哈希不同: {len(hash_diff)}")
    _safe_print(f"  可映射版本: {len(in_branch) + len(missing_branch)}")
    _safe_print(f"    Branch 已有: {len(in_branch)}")
    _safe_print(f"    Branch 缺失: {len(missing_branch)}")
    _safe_print(f"  无版本映射: {len(no_folder)}")
    _safe_print(f"  Hold 谱(仅音频无 eve): {len(hold_audio_only)}")

    if missing_branch:
        _safe_print("\n--- Branch 缺失（可尝试提取）---")
        for row in missing_branch:
            _safe_print(f"  {row['music_id']}\t{row['title']}\t-> {row['folder']}")

    if no_folder:
        _safe_print("\n--- 无版本映射 ---")
        for row in no_folder:
            _safe_print(f"  {row['music_id']}\t{row['title']}")

    if not_in_beyond:
        _safe_print("\n--- BYD 无 IFS（补丁独有）---")
        for row in not_in_beyond:
            _safe_print(f"  {row['music_id']}\t{row['title']}")

    if hash_diff:
        _safe_print("\n--- 与现版 BYD 内容不同 ---")
        for row in hash_diff[:25]:
            _safe_print(f"  {row['music_id']}\t{row['title']}")
        if len(hash_diff) > 25:
            _safe_print(f"  ... 还有 {len(hash_diff) - 25} 首")

    data = {
        "patch_data": str(patch_data),
        "total_ifs": len(patch_ifs),
        "removed": removed,
        "not_in_beyond": not_in_beyond,
        "hash_diff": hash_diff,
        "in_branch": in_branch,
        "missing_branch": missing_branch,
        "no_folder": no_folder,
        "hold_audio_only": hold_audio_only,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n报告: {report_path}")
    return 1 if missing_branch else 0


if __name__ == "__main__":
    raise SystemExit(main())
