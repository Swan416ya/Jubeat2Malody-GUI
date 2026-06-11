#!/usr/bin/env python3
"""批量：RemyWiki 国服独占曲 → 解包 → 转 MCZ → 复制到 mcz-releases/音乐魔方。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _safe_print(*args, **kwargs) -> None:
    text = " ".join(str(a) for a in args)
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), **kwargs)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.cn_bundles import CnBundleIndex, DEFAULT_CN_HOTUPDATE, extract_cn_song, find_cn_hotupdate_dir
from core.malody_writer import convert_song

# RemyWiki AC_jb_China_2025 — Exclusive 音乐魔方 Originals + 国服默认独占授权曲
REMYWIKI_CN_EXCLUSIVE_TITLES = [
    "Dash Dash Groovy Rush!!!",
    "Dim(t)ensions",
    "ln(guis·tics)-jubeat Edit-",
    "Iris",
    "ROM-ANTiC SYND-ROM",
    "The Encounter Code -jubeat Edit-",
    "Obsession",
    "Terminus",
    "House of Deceit",
    "Vania Mania",
    "逆影 〜The Reversed Phantom〜",
    "Remnath -jubeat Edit-",
    # 国服版默认曲（非街机流通）
    "初次见面",
    "袖手旁棺",
    "自电感应",
]

BRANCH_CN_DIR = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch\音乐魔方")
EXTRACT_DIR = ROOT / "debug_out" / "cn_exclusive_extract"
MCZ_TEMP_DIR = ROOT / "debug_out" / "cn_exclusive_mcz"
REPORT_PATH = ROOT / "debug_out" / "cn_exclusive_batch_report.json"


def _norm_title(text: str) -> str:
    return "".join(text.lower().split())


def resolve_hotupdate() -> Path:
    for candidate in (
        DEFAULT_CN_HOTUPDATE,
        Path(r"E:\Program Files (x86)\Jubeat CN"),
        Path(r"E:\Program Files (x86)\Jubeat CN\jubeat-file\jubeat-file"),
    ):
        if not candidate.exists():
            continue
        found = candidate if candidate.name == "100" else find_cn_hotupdate_dir(candidate)
        if found:
            return found
    raise FileNotFoundError("未找到国服 HotUpdate 目录")


def find_exclusive_entries(index: CnBundleIndex) -> list[dict]:
    wanted = {_norm_title(t): t for t in REMYWIKI_CN_EXCLUSIVE_TITLES}
    found: list[dict] = []
    for mid in sorted(index.music_ids):
        info = index.get_song_info(mid)
        name = (info.get("name") or "").strip()
        if not name:
            continue
        key = _norm_title(name)
        if key not in wanted:
            continue
        found.append(
            {
                "music_id": mid,
                "title": name,
                "remywiki_title": wanted[key],
                "artist": info.get("artist_name", ""),
                "has_bgm": mid in index.bgm,
                "has_chart": mid in index.chart_bundle_by_id,
                "has_jacket": mid in index.jackets,
            }
        )
    return found


def main() -> int:
    hotupdate = resolve_hotupdate()
    _safe_print(f"国服资源: {hotupdate}")

    index = CnBundleIndex.scan(hotupdate, load_song_list=True)
    entries = find_exclusive_entries(index)

    matched_norm = {_norm_title(e["title"]) for e in entries}
    missing_titles = [
        t for t in REMYWIKI_CN_EXCLUSIVE_TITLES if _norm_title(t) not in matched_norm
    ]

    _safe_print(f"RemyWiki 独占曲: {len(REMYWIKI_CN_EXCLUSIVE_TITLES)} 首")
    _safe_print(f"本地匹配: {len(entries)} 首")
    if missing_titles:
        _safe_print("本地未找到:", ", ".join(missing_titles))

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    MCZ_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    BRANCH_CN_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "hotupdate": str(hotupdate),
        "matched": entries,
        "missing_titles": missing_titles,
        "converted": [],
        "failed": [],
    }

    for entry in entries:
        mid = entry["music_id"]
        title = entry["title"]
        _safe_print(f"\n=== {title} ({mid}) ===")

        if not entry["has_bgm"] or not entry["has_chart"]:
            msg = f"资源不完整 bgm={entry['has_bgm']} chart={entry['has_chart']}"
            _safe_print("SKIP", msg)
            report["failed"].append({"title": title, "music_id": mid, "reason": msg})
            continue

        song_dir = extract_cn_song(index, mid, EXTRACT_DIR)
        if not song_dir:
            _safe_print("FAIL extract")
            report["failed"].append({"title": title, "music_id": mid, "reason": "解包失败"})
            continue

        mcz = convert_song(song_dir, MCZ_TEMP_DIR, skip_existing=False)
        if not mcz:
            _safe_print("FAIL convert")
            report["failed"].append({"title": title, "music_id": mid, "reason": "转换失败"})
            continue

        dest = BRANCH_CN_DIR / mcz.name
        shutil.copy2(mcz, dest)
        _safe_print(f"OK -> {dest}")
        report["converted"].append(
            {
                "title": title,
                "music_id": mid,
                "mcz": str(dest),
                "source_dir": str(song_dir),
            }
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n完成: 成功 {len(report['converted'])}, 失败 {len(report['failed'])}")
    _safe_print(f"报告: {REPORT_PATH}")
    return 0 if not report["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
