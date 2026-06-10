#!/usr/bin/env python3
"""Jubeat2Malody 命令行工具。

用法示例:
  # 将已解包目录转为 .mcz
  python scripts/jubeat2malody.py convert "debug_out/20000038_隅田川夏恋歌" -o debug_out/mcz

  # 批量转换（遍历子目录）
  python scripts/jubeat2malody.py convert "debug_out" -o debug_out/mcz --batch

  # 搜索国服曲库
  python scripts/jubeat2malody.py cn-search 自电感应

  # 解包国服单曲（music_id 或曲名关键词）
  python scripts/jubeat2malody.py cn-extract 995000003 -o debug_out/cn_extract

  # 解包并直接生成 .mcz
  python scripts/jubeat2malody.py cn-mcz 自电感应 -o debug_out/cn_mcz
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.cn_bundles import (  # noqa: E402
    DEFAULT_CN_HOTUPDATE,
    CnBundleIndex,
    extract_cn_song,
)
from core.malody_writer import convert_song  # noqa: E402


def _iter_song_dirs(path: Path, batch: bool) -> Iterable[Path]:
    if batch:
        for child in sorted(path.iterdir()):
            if child.is_dir() and (child / "song_info.txt").is_file():
                yield child
    else:
        yield path


def cmd_convert(args: argparse.Namespace) -> int:
    src = Path(args.input).resolve()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        print(f"错误: 路径不存在: {src}", file=sys.stderr)
        return 1

    targets = list(_iter_song_dirs(src, args.batch))
    if not targets:
        print(f"错误: 未找到可转换的歌曲目录: {src}", file=sys.stderr)
        return 1

    ok, fail = 0, 0
    for song_dir in targets:
        mcz = convert_song(song_dir, out, skip_existing=args.skip_existing)
        if mcz:
            print(f"OK  {mcz}")
            ok += 1
        else:
            print(f"FAIL {song_dir}", file=sys.stderr)
            fail += 1

    print(f"完成: 成功 {ok}, 失败 {fail}")
    return 0 if fail == 0 else 2


def _load_cn_index(data_dir: Optional[Path]) -> CnBundleIndex:
    hotupdate = data_dir or DEFAULT_CN_HOTUPDATE
    if not Path(hotupdate).exists():
        raise FileNotFoundError(f"国服数据目录不存在: {hotupdate}")
    return CnBundleIndex.scan(Path(hotupdate), load_song_list=True)


def _resolve_cn_music_id(index: CnBundleIndex, query: str) -> Optional[int]:
    query = query.strip()
    if query.isdigit():
        mid = int(query)
        if mid in index.music_ids:
            return mid
        print(f"警告: music_id {mid} 不在曲库中", file=sys.stderr)

    matches: List[tuple[int, str]] = []
    for mid in index.music_ids:
        name = index.get_song_info(mid).get("name", "") or ""
        if query in name or query.lower() in name.lower():
            matches.append((mid, name))

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0][0]

    print("匹配到多首曲目，请指定 music_id:", file=sys.stderr)
    for mid, name in matches:
        print(f"  {mid}  {name}", file=sys.stderr)
    return None


def cmd_cn_search(args: argparse.Namespace) -> int:
    try:
        index = _load_cn_index(args.data_dir)
    except FileNotFoundError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    query = args.query.strip()
    shown = 0
    for mid in sorted(index.music_ids):
        info = index.get_song_info(mid)
        name = info.get("name", "") or ""
        artist = info.get("artist_name", "") or ""
        if query and query not in name and query not in artist:
            continue
        levels = info.get("levels", {})
        lv = " / ".join(
            f"{d.upper()} {levels.get(d.lower(), '-')}"
            for d in ("bsc", "adv", "ext")
            if levels.get(d.lower())
        )
        bpm = info.get("bpm_max") or info.get("bpm_min") or ""
        print(f"{mid}\t{name}\t{artist}\tBPM {bpm}\t{lv}")
        shown += 1

    if shown == 0:
        print("未找到匹配曲目", file=sys.stderr)
        return 1
    print(f"共 {shown} 首")
    return 0


def cmd_cn_extract(args: argparse.Namespace) -> int:
    try:
        index = _load_cn_index(args.data_dir)
    except FileNotFoundError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    mid = _resolve_cn_music_id(index, args.query)
    if mid is None:
        print(f"错误: 未找到曲目: {args.query}", file=sys.stderr)
        return 1

    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    song_dir = extract_cn_song(index, mid, out)
    if not song_dir:
        print(f"错误: 解包失败 music_id={mid}", file=sys.stderr)
        return 1

    info = index.get_song_info(mid)
    print(f"已解包: {song_dir}")
    print(f"曲名: {info.get('name', '')}")
    return 0


def cmd_cn_mcz(args: argparse.Namespace) -> int:
    try:
        index = _load_cn_index(args.data_dir)
    except FileNotFoundError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    mid = _resolve_cn_music_id(index, args.query)
    if mid is None:
        print(f"错误: 未找到曲目: {args.query}", file=sys.stderr)
        return 1

    extract_out = Path(args.extract_dir).resolve()
    mcz_out = Path(args.output).resolve()
    extract_out.mkdir(parents=True, exist_ok=True)
    mcz_out.mkdir(parents=True, exist_ok=True)

    song_dir = extract_cn_song(index, mid, extract_out)
    if not song_dir:
        print(f"错误: 解包失败 music_id={mid}", file=sys.stderr)
        return 1

    mcz = convert_song(song_dir, mcz_out)
    if not mcz:
        print(f"错误: 转换失败 {song_dir}", file=sys.stderr)
        return 1

    print(f"已生成: {mcz}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jubeat2malody",
        description="Jubeat / 国服谱面解包与 Malody .mcz 转换 CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_convert = sub.add_parser("convert", help="将已解包歌曲目录转为 .mcz")
    p_convert.add_argument("input", help="歌曲目录，或含多首子目录的父目录（配合 --batch）")
    p_convert.add_argument("-o", "--output", required=True, help=".mcz 输出目录")
    p_convert.add_argument(
        "--batch",
        action="store_true",
        help="批量模式：遍历 input 下含 song_info.txt 的子目录",
    )
    p_convert.add_argument(
        "--skip-existing",
        action="store_true",
        help="跳过已存在的 .mcz",
    )
    p_convert.set_defaults(func=cmd_convert)

    p_search = sub.add_parser("cn-search", help="搜索国服曲库")
    p_search.add_argument("query", nargs="?", default="", help="曲名/曲师关键词（留空列出全部）")
    p_search.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=f"国服 HotUpdate 目录（默认 {DEFAULT_CN_HOTUPDATE}）",
    )
    p_search.set_defaults(func=cmd_cn_search)

    p_extract = sub.add_parser("cn-extract", help="解包国服单曲")
    p_extract.add_argument("query", help="music_id 或曲名关键词")
    p_extract.add_argument("-o", "--output", required=True, help="解包输出目录")
    p_extract.add_argument("--data-dir", type=Path, default=None, help="国服 HotUpdate 目录")
    p_extract.set_defaults(func=cmd_cn_extract)

    p_mcz = sub.add_parser("cn-mcz", help="解包国服单曲并生成 .mcz")
    p_mcz.add_argument("query", help="music_id 或曲名关键词")
    p_mcz.add_argument("-o", "--output", required=True, help=".mcz 输出目录")
    p_mcz.add_argument(
        "--extract-dir",
        default=str(ROOT / "debug_out" / "cn_cli_extract"),
        help="中间解包目录",
    )
    p_mcz.add_argument("--data-dir", type=Path, default=None, help="国服 HotUpdate 目录")
    p_mcz.set_defaults(func=cmd_cn_mcz)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
