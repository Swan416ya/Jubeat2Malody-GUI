"""日版街机曲绘后处理。"""

from __future__ import annotations

from pathlib import Path


def fix_arcade_jacket_invert(image_path: Path) -> bool:
    """日版 ifstools/texbin 解码曲绘会呈反色，对 RGB 通道 invert 还原。"""
    if not image_path.is_file():
        return False
    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as im:
            bands = im.getbands()
            if "A" in bands:
                rgba = im.convert("RGBA")
                r, g, b, a = rgba.split()
                inverted = ImageOps.invert(Image.merge("RGB", (r, g, b)))
                r2, g2, b2 = inverted.split()
                result = Image.merge("RGBA", (r2, g2, b2, a))
            else:
                result = ImageOps.invert(im.convert("RGB"))

            ext = image_path.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                result.convert("RGB").save(image_path, "JPEG", quality=95)
            else:
                result.save(image_path, "PNG")
        return True
    except Exception:
        return False
