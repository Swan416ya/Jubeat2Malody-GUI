#!/usr/bin/env python3
"""提取样例曲绘，生成多种颜色处理对比图供人工挑选。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageOps

from core.unpacker import (
    _extract_jacket_image,
    _find_jacket_resource,
    build_jacket_index,
    extract_song,
    find_metadata_xml,
    load_music_info,
    load_word_dictionary,
    load_word_info,
)
from core.texbin_extractor import extract_texbin_png

DATA_DIR = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\contents\data")
OUT_DIR = ROOT / "debug_out" / "jacket_compare"
SAMPLES = [
    (11000104, "魔法少女とチョコレゐト", "beyond-ave"),
    (11000023, "ヒトガタ", "ave"),
    (11000068, "fallen leaves", "beyond-ave"),
    (11000001, "Insanity: Luna", "ave"),
]


def _apply_variant(im: Image.Image, name: str) -> Image.Image:
    rgba = im.convert("RGBA")
    r, g, b, a = rgba.split()
    rgb = Image.merge("RGB", (r, g, b))

    if name == "raw":
        return rgba
    if name == "invert":
        inv = ImageOps.invert(rgb)
        r2, g2, b2 = inv.split()
        return Image.merge("RGBA", (r2, g2, b2, a))
    if name == "swap_rb":
        return Image.merge("RGBA", (b, g, r, a))
    if name == "swap_rb_invert":
        inv = ImageOps.invert(Image.merge("RGB", (b, g, r)))
        r2, g2, b2 = inv.split()
        return Image.merge("RGBA", (r2, g2, b2, a))
    if name == "invert_swap_rb":
        inv = ImageOps.invert(rgb)
        r2, g2, b2 = inv.split()
        return Image.merge("RGBA", (b2, g2, r2, a))
    if name == "neg_alpha_rgb":
        # 部分 ifstools 画布：RGB 正常但需按 alpha 反相
        inv = ImageOps.invert(rgb)
        r2, g2, b2 = inv.split()
        return Image.merge("RGBA", (r2, g2, b2, a))
    raise ValueError(name)


VARIANTS = [
    "raw",
    "invert",
    "swap_rb",
    "swap_rb_invert",
    "invert_swap_rb",
]


def _extract_raw_jacket(music_id: int, data_dir: Path, jacket_index: dict) -> Path | None:
    """解包曲绘但不走 jacket_fixup。"""
    wp = find_metadata_xml(data_dir, "word_info.xml")
    wd = load_word_dictionary(wp) if wp else {}
    mp = find_metadata_xml(data_dir, "music_info.xml")
    mi = load_music_info(mp, word_dict=wd) if mp else {}
    wi = load_word_info(wp) if wp else {}

    ifs_files = list(data_dir.rglob(f"*{music_id}_msc.ifs"))
    if not ifs_files:
        return None
    ifs_path = ifs_files[0]

    work = OUT_DIR / f"_work_{music_id}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    jacket_path = _find_jacket_resource(
        music_id, data_dir, msc_ifs_path=ifs_path, jacket_index=jacket_index
    )
    if jacket_path:
        # 临时禁用 fix：直接调用内部逻辑的手动版
        if jacket_path.suffix.lower() == ".bin" and "bnr" in jacket_path.name.lower():
            png_data = extract_texbin_png(jacket_path, music_id=music_id)
            if png_data:
                dest = work / f"jkt_{music_id}.png"
                dest.write_bytes(png_data)
                return dest
        ok, fname = _extract_jacket_image(jacket_path, work, music_id)
        if ok:
            # _extract_jacket_image 现在会 invert — 重新从 temp 拿 raw 需绕过
            pass

    # 完整解包再从目录找图（会触发 fix，下面会读 fix 后的）
    song_dir = extract_song(
        ifs_path, mi, work, ifs_dir=ifs_path.parent, word_info=wi, jacket_index=jacket_index
    )
    if not song_dir:
        return None
    for p in sorted(song_dir.glob("jkt_*")):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            return p
    return None


def _extract_raw_no_fixup(music_id: int, data_dir: Path, jacket_index: dict) -> Path | None:
    """完全绕过 fix_arcade_jacket_colors 提取原始曲绘。"""
    from core.unpacker import extract_ifs, _find_images_in_dir, _pick_best_jacket

    ifs_files = list(data_dir.rglob(f"*{music_id}_msc.ifs"))
    if not ifs_files:
        return None
    ifs_path = ifs_files[0]
    work = OUT_DIR / f"_raw_{music_id}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    jacket_path = _find_jacket_resource(
        music_id, data_dir, msc_ifs_path=ifs_path, jacket_index=jacket_index
    )
    if jacket_path and jacket_path.suffix.lower() == ".bin" and "bnr" in jacket_path.name.lower():
        png_data = extract_texbin_png(jacket_path, music_id=music_id)
        if png_data:
            dest = work / "source.png"
            dest.write_bytes(png_data)
            return dest

    if jacket_path:
        jkt_temp = work / "_jkt_temp"
        jkt_temp.mkdir(parents=True, exist_ok=True)
        try:
            extract_ifs(
                jacket_path, jkt_temp,
                tex_only=True, dump_canvas=True, rename_dupes=True,
            )
            images = _find_images_in_dir(jkt_temp)
            best = _pick_best_jacket(images, music_id)
            if best:
                dest = work / "source.png"
                shutil.copy2(best, dest)
                return dest
        finally:
            shutil.rmtree(jkt_temp, ignore_errors=True)

    # texbin index path already tried; try msc ifs textures
    msc_temp = work / "_msc"
    msc_temp.mkdir(parents=True, exist_ok=True)
    extract_ifs(ifs_path, msc_temp, tex_only=True, dump_canvas=True)
    images = _find_images_in_dir(msc_temp, exclude_music_id=music_id)
    best = _pick_best_jacket(images, music_id)
    if best:
        dest = work / "source.png"
        shutil.copy2(best, dest)
        return dest
    return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jacket_index = build_jacket_index(DATA_DIR)

    print(f"输出目录: {OUT_DIR.resolve()}")
    print("生成对比图...")

    for music_id, title, tag in SAMPLES:
        raw_path = _extract_raw_no_fixup(music_id, DATA_DIR, jacket_index)
        if not raw_path:
            print(f"  [跳过] {title} ({music_id}) — 未找到曲绘")
            continue

        with Image.open(raw_path) as im:
            song_dir = OUT_DIR / f"{music_id}_{tag}"
            song_dir.mkdir(parents=True, exist_ok=True)
            for variant in VARIANTS:
                out = song_dir / f"{variant}.png"
                result = _apply_variant(im, variant)
                result.save(out, "PNG")
            # 也保存一份当前流程产物（含 invert fix）
            from core.jacket_fixup import fix_arcade_jacket_colors

            current = song_dir / "current_pipeline.png"
            shutil.copy2(raw_path, current)
            fix_arcade_jacket_colors(current)

        print(f"  [OK] {title} -> {song_dir.name}/")

    print("\n对比文件夹:")
    for d in sorted(OUT_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("_"):
            files = ", ".join(p.name for p in sorted(d.glob("*.png")))
            print(f"  {d.name}: {files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
