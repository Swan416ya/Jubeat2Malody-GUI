"""
Jubeat / Gitadora texbin (.bin) 纹理解包

Beyond Ave 及新版 Jubeat 的曲绘存放在:
  data/d3/model/tex_l44_bnr_big_id{music_id}.bin

格式参考: littlecxm/gitadora-textool (PXET 容器 + TDXT 纹理)
"""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path
from typing import Optional

try:
    from ifstools.handlers import lz77
    from ifstools.handlers.image_decoders import decode_dxt5, encode_png
    HAS_IFSTOOLS = True
except ImportError:
    HAS_IFSTOOLS = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class TexbinError(RuntimeError):
    pass


def _read_i32(data: bytes, offset: int, big_endian: bool) -> int:
    fmt = ">I" if big_endian else "<I"
    return struct.unpack_from(fmt, data, offset)[0]


def _read_i16(data: bytes, offset: int, big_endian: bool) -> int:
    fmt = ">H" if big_endian else "<H"
    return struct.unpack_from(fmt, data, offset)[0]


def _decompress_lz77(blob: bytes) -> bytes:
    if not HAS_IFSTOOLS:
        raise TexbinError("ifstools 未安装，无法解压 texbin")
    if len(blob) < 8:
        return blob
    comp_size = struct.unpack(">I", blob[4:8])[0]
    if comp_size == 0:
        decomp_size = struct.unpack(">I", blob[:4])[0]
        return blob[8 : 8 + decomp_size]
    return lz77.decompress(blob[8 : 8 + comp_size])


def _decode_tdxt_to_image(tdxt: bytes) -> Image.Image:
    if not HAS_PIL:
        raise TexbinError("Pillow 未安装，无法解码纹理")

    if tdxt[:4] not in (b"TDXT", b"TXDT"):
        raise TexbinError(f"未知纹理头: {tdxt[:4]!r}")

    endian2 = struct.unpack_from("<I", tdxt, 8)[0]
    big_endian = endian2 == 0x00010100

    data_size = _read_i32(tdxt, 0x0C, big_endian) - 0x40
    width = _read_i16(tdxt, 0x10, big_endian)
    height = _read_i16(tdxt, 0x12, big_endian)

    if big_endian:
        fmt = tdxt[0x14]
    else:
        fmt = tdxt[0x17]

    bitmap = tdxt[0x40 : 0x40 + data_size]
    if width <= 0 or height <= 0:
        raise TexbinError(f"无效尺寸: {width}x{height}")

    if fmt == 0x10:
        # BGRA8888
        return Image.frombytes("RGBA", (width, height), bitmap, "raw", "BGRA")

    if fmt == 0x0E:
        # BGR888
        img = Image.frombytes("RGB", (width, height), bitmap, "raw", "BGR")
        return img.convert("RGBA")

    if fmt == 0x11:
        # BGR 4-bit indexed + palette
        pixel_bytes = width * height // 2
        pixels = bitmap[:pixel_bytes]
        palette_raw = bitmap[pixel_bytes + 0x14 :]
        palette = []
        for i in range(0, len(palette_raw) - 3, 4):
            b, g, r, a = palette_raw[i : i + 4]
            palette.append((r, g, b, a if a else 255))

        if not palette:
            raise TexbinError("4-bit 纹理缺少调色板")

        rgba = bytearray(width * height * 4)
        for py in range(height):
            for px in range(width):
                byte = pixels[(py * width + px) // 2]
                nibble = byte >> 4 if px % 2 == 0 else byte & 0x0F
                if nibble >= len(palette):
                    continue
                r, g, b, a = palette[nibble]
                o = (py * width + px) * 4
                rgba[o : o + 4] = (r, g, b, a)

        return Image.frombytes("RGBA", (width, height), bytes(rgba))

    if fmt in (0x1A, 0x18, 0x16) and HAS_IFSTOOLS:
        # DXT1 / DXT3 / DXT5
        class _ImgSize:
            def __init__(self, w: int, h: int):
                self.img_size = (w, h)
                self.name = "texbin"

        if fmt == 0x1A:
            return decode_dxt5(_ImgSize(width, height), bitmap)
        raise TexbinError(f"暂不支持的 DXT 格式: {fmt:#x}")

    raise TexbinError(f"暂不支持的纹理格式: {fmt:#x}")


def _parse_pman_names(data: bytes, name_offset: int) -> list[str]:
    if data[name_offset : name_offset + 4] != b"PMAN":
        return []
    file_count = struct.unpack_from("<I", data, name_offset + 16)[0]
    names: list[str] = []
    entry_base = name_offset + 0x1C
    for i in range(file_count):
        eoff = entry_base + i * 12
        str_off = struct.unpack_from("<I", data, eoff + 8)[0]
        start = name_offset + str_off
        end = data.find(b"\x00", start)
        if end < 0:
            end = start + 64
        names.append(data[start:end].decode("ascii", errors="replace"))
    return names


def extract_texbin_png(texbin_path: Path) -> Optional[bytes]:
    """从 texbin 文件提取 PNG 字节，失败返回 None"""
    if not texbin_path.is_file():
        return None
    if texbin_path.stat().st_size <= 64:
        return None

    try:
        data = texbin_path.read_bytes()
        if data[:4] != b"PXET":
            return None

        file_count = struct.unpack_from("<q", data, 20)[0]
        if file_count <= 0:
            return None

        data_entry_offset = struct.unpack_from("<I", data, 60)[0]
        _, comp_size, blob_offset = struct.unpack_from("<3I", data, data_entry_offset)

        comp = data[blob_offset : blob_offset + comp_size]
        tdxt = _decompress_lz77(comp)
        image = _decode_tdxt_to_image(tdxt)

        if HAS_IFSTOOLS:
            return encode_png(image)

        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _texbin_model_roots(data_dir: Path) -> list[Path]:
    """收集曲绘 texbin 可能出现的目录（含在线 datapackage 缓存）"""
    data_dir = data_dir.resolve()
    roots: list[Path] = []

    def _add(path: Path) -> None:
        if path.is_dir() and path not in roots:
            roots.append(path)

    _add(data_dir / "data" / "d3" / "model")
    _add(data_dir / "d3" / "model")
    # Spice/Konami 在线包: contents/datapackage/data → 挂载为 /vfs_datapackage
    _add(data_dir / "datapackage" / "data" / "d3" / "model")
    if data_dir.name == "contents":
        _add(data_dir / "datapackage" / "data" / "d3" / "model")

    for root in data_dir.parents:
        _add(root / "data" / "d3" / "model")
        _add(root / "datapackage" / "data" / "d3" / "model")
        if len(roots) >= 10:
            break

    return roots


def find_bnr_big_texbin(data_dir: Path, music_id: int) -> Optional[Path]:
    """查找新版 Jubeat 曲绘 texbin 路径"""
    id_str = str(music_id)
    patterns = [
        f"tex_l44_bnr_big_id{id_str}.bin",
        f"tex_l44av_bnr_big_id{id_str}.bin",
        f"tex_l44*_bnr_big_id{id_str}.bin",
    ]

    search_roots = _texbin_model_roots(data_dir)

    for root in search_roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            if "*" in pattern:
                matches = sorted(root.glob(pattern))
            else:
                p = root / pattern
                matches = [p] if p.is_file() else []
            for match in matches:
                if match.stat().st_size > 64:
                    return match
    return None


def build_texbin_jacket_index(data_dir: Path) -> dict[int, Path]:
    """扫描 d3/model（及 datapackage 缓存）下所有 bnr_big 曲绘 texbin"""
    index: dict[int, Path] = {}
    for root in _texbin_model_roots(data_dir):
        for path in root.glob("tex_l44*_bnr_big_id*.bin"):
            if path.stat().st_size <= 64:
                continue
            stem = path.stem
            digits = stem.rsplit("_id", 1)
            if len(digits) != 2:
                continue
            try:
                music_id = int(digits[1])
            except ValueError:
                continue
            if music_id not in index:
                index[music_id] = path
    return index


def datapackage_status(data_dir: Path) -> dict:
    """检查 datapackage 在线资源缓存状态"""
    dp_data = data_dir.resolve() / "datapackage" / "data"
    if not dp_data.is_dir():
        return {"exists": False, "jacket_bins": 0}

    jacket_bins = [
        p for p in dp_data.rglob("tex_l44*_bnr_big_id*.bin")
        if p.is_file() and p.stat().st_size > 64
    ]
    return {
        "exists": True,
        "jacket_bins": len(jacket_bins),
        "path": str(dp_data),
    }
