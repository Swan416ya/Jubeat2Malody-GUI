#!/usr/bin/env python3
"""核对 Festo 本地数据：相对 Beyond Ave 独有且 Branch 是否已提取。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.recover_from_legacy_data import _branch_has, _load_catalog
from core.song_debut import resolve_debut_folder_for_id

FESTO = Path(r"E:\Program Files (x86)\Jubeat Festo\L44-011-2022052400\contents\data")
BEYOND = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
REPORT = ROOT / "debug_out" / "festo_vs_byd_audit.json"


def _safe_print(*args) -> None:
    text = " ".join(str(a) for a in args)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), flush=True)


def main() -> int:
    _safe_print("加载 Festo 曲库 ...")
    festo = _load_catalog(FESTO)
    _safe_print("加载 Beyond Ave 曲库 ...")
    beyond = _load_catalog(BEYOND)

    festo_only_ok: list[tuple] = []
    festo_only_no_folder: list[tuple] = []
    festo_only_in_branch: list[tuple] = []
    festo_only_missing: list[tuple] = []

    for mid, entry in sorted(festo.items(), key=lambda x: x[0]):
        if entry.content_removed:
            continue
        cur = beyond.get(mid)
        beyond_gone = cur is None or cur.content_removed
        if not beyond_gone:
            continue

        folder = resolve_debut_folder_for_id(mid, entry.title)
        reason = "byd无数据" if cur is None else "byd版权占位"
        if not folder or folder == "unknown":
            festo_only_no_folder.append((mid, entry.title, reason))
            continue

        festo_only_ok.append((mid, entry.title, folder, reason))
        if _branch_has(entry.title, folder):
            festo_only_in_branch.append((mid, entry.title, folder))
        else:
            festo_only_missing.append((mid, entry.title, folder))

    _safe_print()
    _safe_print("=== Festo 有完整数据、Beyond Ave 无/占位 ===")
    _safe_print(f"总计: {len(festo_only_ok)} 首")
    _safe_print(f"  已在 Branch: {len(festo_only_in_branch)} 首")
    _safe_print(f"  Branch 仍缺失: {len(festo_only_missing)} 首")
    _safe_print(f"  无法映射版本: {len(festo_only_no_folder)} 首")

    if festo_only_missing:
        _safe_print("\n--- Branch 仍缺失（需从 Festo 提取）---")
        for mid, title, folder in festo_only_missing:
            _safe_print(f"  {mid}\t{title}\t-> {folder}")

    if festo_only_no_folder:
        _safe_print("\n--- 无版本映射 ---")
        for mid, title, reason in festo_only_no_folder:
            _safe_print(f"  {mid}\t{title}\t({reason})")

    if not festo_only_missing and not festo_only_no_folder:
        _safe_print("\n结论: Festo 相对 BYD 可提取的曲目已全部进 Branch。")

    data = {
        "festo_only_total": len(festo_only_ok),
        "in_branch": [
            {"music_id": m, "title": t, "folder": f} for m, t, f in festo_only_in_branch
        ],
        "missing_branch": [
            {"music_id": m, "title": t, "folder": f} for m, t, f in festo_only_missing
        ],
        "no_folder": [
            {"music_id": m, "title": t, "reason": r} for m, t, r in festo_only_no_folder
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n报告: {REPORT}")
    return 1 if festo_only_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
