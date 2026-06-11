"""日版街机曲绘后处理。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

JACKET_COLOR_FIX = "swap_rb"


def fix_arcade_jacket_colors(image_path: Path) -> bool:
    """日版 ifstools/texbin 解码曲绘为 BGR 序，交换 R/B 通道还原为 RGB。"""
    if not image_path.is_file():
        return False
    try:
        from PIL import Image

        with Image.open(image_path) as im:
            rgba = im.convert("RGBA")
            r, g, b, a = rgba.split()
            result = Image.merge("RGBA", (b, g, r, a))

            ext = image_path.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                result.convert("RGB").save(image_path, "JPEG", quality=95)
            else:
                result.save(image_path, "PNG")
        return True
    except Exception:
        return False


def apply_arcade_jacket_fix_if_needed(
    image_path: Optional[Path], info: dict
) -> bool:
    """日版曲绘 BGR→RGB；已标记修复过的跳过（避免重复对调）。"""
    if not image_path or not image_path.is_file():
        return False
    if info.get("jacket_color_fix") == JACKET_COLOR_FIX:
        return False
    return fix_arcade_jacket_colors(image_path)
