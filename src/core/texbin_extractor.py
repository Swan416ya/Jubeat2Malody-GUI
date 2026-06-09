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


def _read_i32(data: bytes, offset: int, native_endian: bool) -> int:
    # gitadora-textool: requiresEndianFix=True 时按平台小端读，否则反转字节序
    fmt = "<I" if native_endian else ">I"
    return struct.unpack_from(fmt, data, offset)[0]


def _read_i16(data: bytes, offset: int, native_endian: bool) -> int:
    fmt = "<H" if native_endian else ">H"
    return struct.unpack_from(fmt, data, offset)[0]


def _decompress_lz77(blob: bytes) -> bytes:
    """PXET/texbin 使用的 LZSS，与 ifstools IFS LZ77 不兼容。"""
    if len(blob) < 8:
        return blob

    decomp_size = struct.unpack(">I", blob[:4])[0]
    comp_size = struct.unpack(">I", blob[4:8])[0]
    if comp_size == 0:
        return blob[8 : 8 + decomp_size]

    comp = blob[8 : 8 + comp_size]
    window_data = bytearray(4096)
    output_data = bytearray(decomp_size)
    comp_offset = 0
    decomp_offset = 0
    window = 4078
    control_byte = 0
    bit_count = 0

    while True:
        if bit_count == 0:
            if comp_offset >= comp_size:
                break
            control_byte = comp[comp_offset]
            comp_offset += 1
            bit_count = 8

        if control_byte & 0x01:
            if comp_offset >= comp_size:
                break
            output_data[decomp_offset] = window_data[window] = comp[comp_offset]
            decomp_offset += 1
            window += 1
            comp_offset += 1
            if decomp_offset >= decomp_size:
                break
            window &= 0xFFF
        else:
            if decomp_offset >= decomp_size - 1:
                break
            slide_offset = (
                ((comp[comp_offset + 1] & 0xF0) << 4) | comp[comp_offset]
            ) & 0xFFF
            slide_length = (comp[comp_offset + 1] & 0x0F) + 3
            comp_offset += 2
            if decomp_offset + slide_length > decomp_size:
                slide_length = decomp_size - decomp_offset
            while slide_length > 0:
                output_data[decomp_offset] = window_data[window] = window_data[
                    slide_offset
                ]
                decomp_offset += 1
                window += 1
                slide_offset += 1
                window &= 0xFFF
                slide_offset &= 0xFFF
                slide_length -= 1

        control_byte >>= 1
        bit_count -= 1

    return bytes(output_data)


def _decode_tdxt_to_image(tdxt: bytes) -> Image.Image:
    if not HAS_PIL:
        raise TexbinError("Pillow 未安装，无法解码纹理")

    if tdxt[:4] not in (b"TDXT", b"TXDT"):
        raise TexbinError(f"未知纹理头: {tdxt[:4]!r}")

    requires_endian_fix = struct.unpack_from("<I", tdxt, 8)[0] == 0x00010100

    data_size = _read_i32(tdxt, 0x0C, requires_endian_fix) - 0x40
    width = _read_i16(tdxt, 0x10, requires_endian_fix)
    height = _read_i16(tdxt, 0x12, requires_endian_fix)

    if requires_endian_fix:
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
        # BGR 4-bit indexed + palette (gitadora-textool)
        pixel_bytes = width * height // 2
        pixels = bytearray(bitmap[:pixel_bytes])
        for i in range(len(pixels)):
            b = pixels[i]
            pixels[i] = ((b & 0x0F) << 4) | ((b & 0xF0) >> 4)

        palette_raw = bitmap[pixel_bytes + 0x14 : pixel_bytes + 0x14 + 16 * 4]
        palette = []
        for i in range(0, 64, 4):
            b, g, r, a = palette_raw[i : i + 4]
            palette.append((r, g, b, a if a else 255))

        if not palette:
            raise TexbinError("4-bit 纹理缺少调色板")

        rgba = bytearray(width * height * 4)
        for i in range(width * height):
            byte = pixels[i // 2]
            nibble = byte >> 4 if i % 2 == 0 else byte & 0x0F
            r, g, b, a = palette[nibble]
            o = i * 4
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


def _festo_asset_id(music_id: int) -> Optional[str]:
    """Festo 及以后部分图集用 50000xxx 资源 ID 对应 10000xxx 曲目。"""
    if 10_000_000 <= music_id < 20_000_000:
        return str(50_000_000 + (music_id - 10_000_000))
    return None


def _jacket_id_strings(music_id: int) -> list[str]:
    ids = [str(music_id)]
    festo = _festo_asset_id(music_id)
    if festo:
        ids.append(festo)
    return ids


def _music_id_from_asset_id(asset_id: int) -> Optional[int]:
    if 50_000_000 <= asset_id < 60_000_000:
        return 10_000_000 + (asset_id - 50_000_000)
    if asset_id >= 10_000_000:
        return asset_id
    return None


def _music_id_from_pman_name(name: str) -> Optional[int]:
    upper = name.upper()
    for prefix in ("IDX_MINI_ID", "BNR_BIG_ID", "IDX_ID", "BNR_ID", "LCS_ID"):
        pos = upper.find(prefix)
        if pos < 0:
            continue
        digits = ""
        for ch in upper[pos + len(prefix) :]:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            continue
        try:
            asset_id = int(digits)
        except ValueError:
            continue
        music_id = _music_id_from_asset_id(asset_id)
        if music_id is not None:
            return music_id
    return None


def _jacket_entry_score(name: str, music_id: int) -> int:
    """PMAN 子图名称与 music_id 的匹配分数，越高越优先。"""
    upper = name.upper()
    best = 0
    for id_str in _jacket_id_strings(music_id):
        if f"IDX_MINI_ID{id_str}" in upper:
            best = max(best, 400)
        if f"BNR_BIG_ID{id_str}" in upper:
            best = max(best, 300)
        if f"IDX_ID{id_str}" in upper:
            best = max(best, 250)
        if f"BNR_ID{id_str}" in upper:
            best = max(best, 200)
        if f"ID{id_str}" in upper and "BNR" in upper:
            best = max(best, 100)
    return best


def _pxet_entries(data: bytes) -> list[tuple[str, int, int]]:
    """解析 PXET 内所有子图: (名称, blob_offset, comp_size)"""
    if data[:4] != b"PXET":
        return []

    file_count = struct.unpack_from("<q", data, 20)[0]
    if file_count <= 0:
        return []

    name_offset = struct.unpack_from("<I", data, 52)[0]
    names = _parse_pman_names(data, name_offset)
    data_entry_offset = struct.unpack_from("<I", data, 60)[0]

    entries: list[tuple[str, int, int]] = []
    for i in range(file_count):
        entry_off = data_entry_offset + i * 12
        if entry_off + 12 > len(data):
            break
        _, comp_size, blob_offset = struct.unpack_from("<3I", data, entry_off)
        name = names[i] if i < len(names) else f"entry_{i}"
        entries.append((name, blob_offset, comp_size))
    return entries


def _pick_pxet_entry(
    entries: list[tuple[str, int, int]], music_id: Optional[int]
) -> Optional[tuple[str, int, int]]:
    if not entries:
        return None
    if music_id is None:
        return entries[0]

    best: Optional[tuple[str, int, int]] = None
    best_score = 0
    for entry in entries:
        score = _jacket_entry_score(entry[0], music_id)
        if score > best_score:
            best_score = score
            best = entry
    return best


def _image_from_pxet_blob(data: bytes, blob_offset: int, comp_size: int) -> Image.Image:
    comp = data[blob_offset : blob_offset + comp_size]
    tdxt = _decompress_lz77(comp)
    return _decode_tdxt_to_image(tdxt)


def _encode_image_png(image: Image.Image) -> bytes:
    if HAS_IFSTOOLS:
        return encode_png(image)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


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


def extract_texbin_png(texbin_path: Path, music_id: Optional[int] = None) -> Optional[bytes]:
    """从 texbin 文件提取 PNG 字节，失败返回 None

    支持:
    - 单曲 tex_l44_bnr_big_id{id}.bin
    - 旧曲图集 tex_l44_bnr_j_*.bin 内的 BNR_BIG_ID{id} 子图
    """
    if not texbin_path.is_file():
        return None
    if texbin_path.stat().st_size <= 64:
        return None

    try:
        data = texbin_path.read_bytes()
        if data[:4] != b"PXET":
            return None

        entries = _pxet_entries(data)
        picked = _pick_pxet_entry(entries, music_id)
        if not picked:
            return None

        _, blob_offset, comp_size = picked
        image = _image_from_pxet_blob(data, blob_offset, comp_size)
        return _encode_image_png(image)
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


def _index_pxet_atlas(path: Path, index: dict[int, Path]) -> None:
    """从 PXET 图集 PMAN 名称建立 music_id → 图集路径索引"""
    try:
        data = path.read_bytes()
    except OSError:
        return
    if data[:4] != b"PXET":
        return

    for name, _, _ in _pxet_entries(data):
        music_id = _music_id_from_pman_name(name)
        if music_id is None or music_id in index:
            continue
        if _jacket_entry_score(name, music_id) <= 0:
            continue
        index[music_id] = path


def build_texbin_jacket_index(data_dir: Path) -> dict[int, Path]:
    """扫描 d3/model 下曲绘 texbin（单曲 + 旧曲图集）"""
    index: dict[int, Path] = {}
    atlas_patterns = (
        "tex_l44*_bnr_j_*.bin",
        "tex_l44*_*lcs_j_*.bin",
    )

    for root in _texbin_model_roots(data_dir):
        if not root.is_dir():
            continue

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
            index[music_id] = path

        for pattern in atlas_patterns:
            for path in root.glob(pattern):
                if path.stat().st_size <= 64:
                    continue
                _index_pxet_atlas(path, index)

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
