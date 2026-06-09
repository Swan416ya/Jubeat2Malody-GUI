#!/usr/bin/env python3
"""解包诊断脚本 — 只处理一首歌，打印全部元数据与文件信息。

用法:
  python scripts/debug_unpack_one.py <游戏数据目录> [输出目录] [music_id]

示例:
  python scripts/debug_unpack_one.py "D:/jubeat/contents/data"
  python scripts/debug_unpack_one.py "D:/jubeat/contents/data" "./debug_out" 10000001
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.unpacker import (  # noqa: E402
    _find_jacket_resource,
    _parse_bpm_from_eve,
    _parse_music_id_from_ifs,
    build_jacket_index,
    extract_song,
    find_metadata_xml,
    is_ifs_encrypted,
    load_music_info,
    load_word_dictionary,
    load_word_info,
    resolve_artist,
    resolve_bpm,
    resolve_display_title,
)
from core.texbin_extractor import datapackage_status, find_bnr_big_texbin  # noqa: E402
from core.song_database import get_song_artist, get_song_name, load_reference_tsv  # noqa: E402


def _find_target_ifs(data_dir: Path, music_id: int | None) -> Path | None:
    files = sorted(data_dir.rglob("*_msc.ifs"))
    if not files:
        return None
    if music_id is None:
        return files[0]
    for f in files:
        if _parse_music_id_from_ifs(f) == music_id:
            return f
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="解包一首歌并打印诊断信息")
    parser.add_argument("data_dir", help="游戏数据目录 (如 contents/data)")
    parser.add_argument("output_dir", nargs="?", default="./debug_unpack_out", help="临时输出目录")
    parser.add_argument("music_id", nargs="?", type=int, help="指定 music_id，省略则取第一首")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    if not data_dir.is_dir():
        print(f"[错误] 目录不存在: {data_dir}")
        return 1

    print("=" * 60)
    print("Jubeat 单曲解包诊断")
    print("=" * 60)
    print(f"数据目录: {data_dir.resolve()}")
    print(f"输出目录: {output_dir.resolve()}")

    word_info_path = find_metadata_xml(data_dir, "word_info.xml")
    music_info_path = find_metadata_xml(data_dir, "music_info.xml")
    print(f"\n[元数据文件]")
    print(f"  word_info.xml : {word_info_path or '未找到'}")
    print(f"  music_info.xml: {music_info_path or '未找到'}")

    word_dict = load_word_dictionary(word_info_path) if word_info_path else {}
    print(f"  word_info 词库: {len(word_dict)} 条")
    if word_dict:
        sample_id, sample_text = next(iter(word_dict.items()))
        print(f"  词库样例: {sample_id} -> {sample_text}")

    music_info = {}
    if music_info_path:
        music_info = load_music_info(music_info_path, word_dict=word_dict)
        print(f"  music_info 曲目: {len(music_info)} 首")

    word_info = load_word_info(word_info_path) if word_info_path else {}
    if word_info:
        print(f"  word_info 按曲: {len(word_info)} 首")

    load_reference_tsv()
    msc_files = sorted(data_dir.rglob("*_msc.ifs"))
    print(f"\n[IFS 文件] 共 {len(msc_files)} 个 *_msc.ifs")
    if not msc_files:
        print("[错误] 未找到任何 *_msc.ifs")
        return 1

    target = _find_target_ifs(data_dir, args.music_id)
    if target is None:
        print(f"[错误] 未找到 music_id={args.music_id} 对应的 _msc.ifs")
        return 1

    music_id = _parse_music_id_from_ifs(target)
    print(f"\n[目标曲目]")
    print(f"  IFS 文件 : {target}")
    print(f"  music_id : {music_id}")
    print(f"  加密     : {is_ifs_encrypted(target)}")

    raw_info = music_info.get(music_id, {})
    print(f"\n[music_info 原始字段]")
    if raw_info:
        for key, val in raw_info.items():
            if key != "levels":
                print(f"  {key}: {val}")
        if raw_info.get("levels"):
            print(f"  levels: {raw_info['levels']}")
    else:
        print("  (music_info 中无此 ID)")

    ref_name = get_song_name(music_id)
    ref_artist = get_song_artist(music_id)
    print(f"\n[参考库回退]")
    print(f"  曲名: {ref_name or '(无)'}")
    print(f"  曲师: {ref_artist or '(无)'}")

    jacket_index = build_jacket_index(data_dir)
    print(f"  封面索引: {len(jacket_index)} 个 (含 texbin bnr_big)")
    jacket_path = _find_jacket_resource(
        music_id, data_dir, msc_ifs_path=target, jacket_index=jacket_index,
    )
    texbin_path = find_bnr_big_texbin(data_dir, music_id)
    print(f"\n[曲绘资源]")
    print(f"  索引命中 : {jacket_path or '未找到'}")
    print(f"  texbin   : {texbin_path or '未找到'}")
    if music_id not in music_info:
        print("  说明: 此曲不在 Beyond Ave 的 music_info.xml 中（旧曲常见）")
    dp = datapackage_status(data_dir)
    print(f"\n[DataPackage 在线缓存]")
    print(f"  目录: {dp.get('path', '无')}")
    print(f"  已下载曲绘: {dp.get('jacket_bins', 0)} 个")
    if not jacket_path and not texbin_path:
        print("  说明: Beyond Ave 将谱面与曲绘分开存储:")
        print("    - 谱面: ifs_pack/{id}_msc.ifs (基础包内，共 1754)")
        print("    - 曲绘: d3/model/tex_l44_bnr_big_id{id}.bin (基础包约 1116 首)")
        print("    - 旧曲曲绘: 启动时通过 DataPackage 从服务器下载到")
        print("      contents/datapackage/data/ (你当前为 0，见 log.txt)")
        print("  若游戏内仍能看到旧曲封面，可能是默认占位图或曾成功下载过缓存")
    if jacket_path and jacket_path.suffix.lower() == ".ifs":
        print(f"  封面加密: {is_ifs_encrypted(jacket_path)}")

    print(f"\n[开始解包...]")
    output_dir.mkdir(parents=True, exist_ok=True)
    song_dir = extract_song(
        target, music_info, output_dir,
        ifs_dir=data_dir, word_info=word_info,
        jacket_index=jacket_index,
    )
    if not song_dir:
        print("[错误] extract_song 返回 None")
        return 1

    print(f"  输出目录: {song_dir}")
    info_txt = song_dir / "song_info.txt"
    if info_txt.exists():
        print(f"\n[song_info.txt]")
        print(info_txt.read_text(encoding="utf-8"))

    print(f"\n[解包文件列表]")
    images = []
    for f in sorted(song_dir.iterdir()):
        if f.is_file():
            tag = ""
            if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                tag = " [图片]"
                images.append(f.name)
            print(f"  {f.name}{tag} ({f.stat().st_size} bytes)")

    bpm = resolve_bpm(raw_info)
    if bpm <= 0 and song_dir:
        bpm = _parse_bpm_from_eve(song_dir)
    print(f"\n[结果摘要]")
    print(f"  显示曲名: {resolve_display_title(raw_info) or ref_name or f'unknown_{music_id}'}")
    print(f"  显示曲师: {resolve_artist(raw_info) or ref_artist or '(空)'}")
    print(f"  BPM      : {bpm if bpm > 0 else '无 (music_info 无此曲，且 EVE 无 TEMPO)'}")
    print(f"  曲绘图片: {', '.join(images) if images else '无'}")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
