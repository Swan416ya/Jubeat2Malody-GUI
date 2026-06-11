"""
Jubeat IFS 解包模块

从 Jubeat 游戏文件中提取谱面 (EVE)、音频 (BGM)、封面图片和元数据。
依赖: ifstools (IFS 解包), 标准库 (BMP→WAV, music_info.xml 解析)
"""

import os
import re
import struct
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Optional, List, Tuple

ProgressReporter = Callable[[str, int], None]

try:
    import ifstools
    HAS_IFSTOOLS = True
except ImportError:
    HAS_IFSTOOLS = False


def decode_name_string(encoded: str) -> str:
    """解码 music_info.xml 中的 name_string (Shift-JIS 编码的十六进制字符串)

    多种编码尝试: Shift-JIS → CP932 → EUC-JP → UTF-8 → 原始回退
    """
    if not encoded or not encoded.strip():
        return ""

    encoded = encoded.strip()

    # 尝试十六进制解码
    try:
        raw = bytes.fromhex(encoded)
        for encoding in ("shift_jis", "cp932", "euc_jp", "utf-8"):
            try:
                result = raw.decode(encoding)
                if result and not any(ord(c) < 0x20 and c not in "\n\r\t" for c in result):
                    return result
            except (UnicodeDecodeError, ValueError):
                continue
    except ValueError:
        pass

    # 可能本身就是明文（含日文/中文），但不要将未解码的 hex 串当作曲名
    if re.fullmatch(r"[0-9a-fA-F]+", encoded):
        return ""

    if any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in encoded):
        return encoded

    # 含空格的英文/罗马音曲名
    if re.search(r"[A-Za-z]", encoded) and " " in encoded:
        return encoded

    return encoded


def _find_metadata_xml_in_tree(root: Path, filename: str) -> Optional[Path]:
    """在单个目录树下查找 metadata XML"""
    direct = root / filename
    if direct.is_file():
        return direct

    subdir = filename.replace(".xml", "")
    nested = root / subdir / filename
    if nested.is_file():
        return nested

    matches = sorted(root.rglob(filename))
    if not matches:
        return None

    for path in matches:
        if subdir in path.parts:
            return path
    return matches[0]


def find_metadata_xml(root: Path, filename: str, search_parents: int = 6) -> Optional[Path]:
    """在 Jubeat 数据目录中查找 music_info.xml / word_info.xml

    常见路径:
    - {root}/music_info/music_info.xml
    - {root}/word_info/word_info.xml
    - 向上搜索父目录 (用户可能只选了 ifs_pack 子目录)
    """
    if not root.exists():
        return None

    current = root.resolve()
    for _ in range(search_parents + 1):
        found = _find_metadata_xml_in_tree(current, filename)
        if found:
            return found
        if current.parent == current:
            break
        current = current.parent
    return None


def _parse_xml_float(elem: Optional[ET.Element], default: float = 0.0) -> float:
    """安全解析 XML 元素中的数值（支持整数和小数）"""
    if elem is None or not elem.text:
        return default
    try:
        return float(elem.text.strip())
    except ValueError:
        return default


def _parse_bpm_fields(
    bpm_min_elem: Optional[ET.Element], bpm_max_elem: Optional[ET.Element]
) -> tuple[float, float]:
    """解析 music_info.xml 中的 BPM 字段

    兼容:
    - 微秒/拍 (如 3000000)
    - 直接 BPM 浮点 (Beyond Ave: bpm_max=140, bpm_min=-1)
    """
    bpm_min_raw = _parse_xml_float(bpm_min_elem)
    bpm_max_raw = _parse_xml_float(bpm_max_elem)

    if bpm_max_raw > 1000:
        bpm_min = round(60_000_000 / bpm_min_raw, 2) if bpm_min_raw > 0 else 0.0
        bpm_max = round(60_000_000 / bpm_max_raw, 2) if bpm_max_raw > 0 else 0.0
    else:
        bpm_min = bpm_min_raw
        bpm_max = bpm_max_raw

    # Beyond Ave 等版本: bpm_min=-1 表示无变速，仅用 bpm_max
    if bpm_max > 0 and bpm_min < 0:
        bpm_min = bpm_max

    return bpm_min, bpm_max


def resolve_bpm(info: dict) -> float:
    """从元数据字典取得有效 BPM 值"""
    bpm_min = float(info.get("bpm_min") or 0)
    bpm_max = float(info.get("bpm_max") or 0)
    if bpm_max > 0:
        return bpm_max
    if bpm_min > 0:
        return bpm_min
    return 0.0


def _parse_bpm_from_eve(song_dir: Path) -> float:
    """从解包后的 EVE 谱面读取首个 TEMPO 作为 BPM 回退"""
    from .song_resources import DIFFICULTIES, resolve_eve_path

    for difficulty in DIFFICULTIES:
        eve_path = resolve_eve_path(song_dir, difficulty)
        if not eve_path:
            continue
        try:
            for line in eve_path.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3 and parts[1].upper() == "TEMPO":
                    tempo = float(parts[2])
                    if tempo > 1000:
                        return round(60_000_000 / tempo, 2)
                    return round(tempo, 2)
        except (OSError, ValueError, ZeroDivisionError):
            continue
    return 0.0


def _is_katakana_dominant(text: str) -> bool:
    """判断字符串是否以片假名为主（读音名，非正式曲名）"""
    if not text:
        return False
    katakana = 0
    other_cjk = 0
    for c in text:
        if "\u30a0" <= c <= "\u30ff":
            katakana += 1
        elif "\u3040" <= c <= "\u309f" or "\u4e00" <= c <= "\u9fff":
            other_cjk += 1
    return katakana > 0 and other_cjk == 0


def resolve_display_title(info: dict) -> str:
    """选择最适合显示的曲名（优先正式标题，避免纯片假名读音名）"""
    candidates = [
        info.get("title_name"),
        info.get("name"),
        info.get("ascii_name"),
        info.get("japanese_name"),
        info.get("reading_name"),
        info.get("copyright_name"),
    ]
    for name in candidates:
        if name and not str(name).startswith("unknown_") and not _is_katakana_dominant(name):
            return name
    for name in candidates:
        if name and not str(name).startswith("unknown_"):
            return name
    return info.get("name", "")


def resolve_artist(info: dict) -> str:
    """选择艺术家名（copyright_name 是版权方 KONAMI，不是曲师）"""
    for key in ("artist", "artist_name"):
        value = (info.get(key) or "").strip()
        if not value:
            continue
        upper = value.upper()
        if upper in ("KONAMI", "KONAMI AMUSEMENT", "COPYRIGHT"):
            continue
        if value.startswith("unknown_") or upper == "UNKNOWN":
            continue
        return value
    return ""


def _parse_xml_root(xml_path: Path) -> ET.Element:
    """解析 XML，兼容 UTF-8 / Shift-JIS 等编码（参考 bemaniutils）"""
    try:
        return ET.parse(xml_path).getroot()
    except ET.ParseError:
        pass

    raw = xml_path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp932", "shift_jis", "shift_jisx0213", "euc_jp"):
        try:
            text = raw.decode(encoding)
            return ET.fromstring(text)
        except (UnicodeDecodeError, ET.ParseError):
            continue

    raise ValueError(f"无法解析 XML: {xml_path}")


def _parse_music_id_from_ifs(ifs_path: Path) -> int:
    """从 IFS 文件名提取 music_id（兼容 10000001_msc / d123_10000001_msc 等）"""
    match = re.search(r"(\d{5,10})_msc\.ifs$", ifs_path.name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    nums = re.findall(r"\d{5,10}", ifs_path.stem)
    if nums:
        return int(nums[-1])
    return 0


def _parse_music_id_from_jacket(path: Path) -> int:
    """从封面资源文件名提取 music_id"""
    match = re.search(
        r"(\d{5,10})_(?:jkt|ifs)\.(?:ifs|bin)$", path.name, re.IGNORECASE
    )
    if match:
        return int(match.group(1))
    return 0


def build_jacket_index(data_dir: Path) -> dict[int, Path]:
    """一次性扫描目录，建立 music_id → 封面资源路径索引

    支持:
    - 旧版: ifs_pack/{id}_jkt.ifs
    - Beyond Ave 等: data/d3/model/tex_l44_bnr_big_id{id}.bin
    """
    from .texbin_extractor import build_texbin_jacket_index

    index: dict[int, Path] = build_texbin_jacket_index(data_dir)
    data_dir = data_dir.resolve()

    ifs_pack_dirs = sorted(p for p in data_dir.rglob("ifs_pack") if p.is_dir())
    scan_roots = ifs_pack_dirs if ifs_pack_dirs else [data_dir]

    patterns = ("*_jkt.ifs", "*_jkt.bin", "*_ifs.ifs")
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for pattern in patterns:
            for candidate in scan_root.rglob(pattern):
                music_id = _parse_music_id_from_jacket(candidate)
                if not music_id or music_id in index:
                    continue
                if candidate.suffix.lower() == ".ifs" and is_ifs_content_removed(candidate):
                    continue
                index[music_id] = candidate

    return index


def _resolve_word_id(
    data_elem: ET.Element, field_names: List[str], word_dict: dict
) -> str:
    """通过 word_id 字段从 word_info 字典查找文本"""
    for fname in field_names:
        elem = data_elem.find(fname)
        if elem is None or not elem.text:
            continue
        raw = elem.text.strip()
        try:
            word_id = int(raw)
            if word_id in word_dict:
                return word_dict[word_id]
        except ValueError:
            decoded = decode_name_string(raw) or raw
            if decoded:
                return decoded
    return ""


def _extract_text_field(data_elem: ET.Element, field_names: List[str]) -> str:
    """从 XML 元素中提取并解码文本字段"""
    for fname in field_names:
        elem = data_elem.find(fname)
        if elem is not None and elem.text:
            decoded = decode_name_string(elem.text) or elem.text.strip()
            if decoded:
                return decoded
    return ""


def _resolve_ids_from_word_dict(
    data_elem: ET.Element, word_dict: dict
) -> tuple[str, str]:
    """扫描 music_info 中所有 *_id 字段，从 word_info 词库解析曲名/曲师"""
    title = ""
    artist = ""

    for child in data_elem:
        tag = child.tag.lower()
        if not tag.endswith("_id") or not child.text:
            continue
        try:
            word_id = int(child.text.strip())
        except ValueError:
            continue
        text = word_dict.get(word_id, "")
        if not text:
            continue

        if "artist" in tag:
            artist = artist or text
        elif any(k in tag for k in ("title", "name", "word", "string")):
            if "ascii" in tag or "yomi" in tag or "reading" in tag:
                continue
            title = title or text

    return title, artist


def load_word_dictionary(word_info_path: Path) -> dict:
    """解析 word_info.xml 中的全局词库 {word_id: text}

    Jubeat 曲名/曲师通常通过 word_id 引用此词库，而非直接写在 music_info.xml 中。
    """
    word_dict = {}
    if not word_info_path.exists():
        return word_dict

    try:
        root = _parse_xml_root(word_info_path)
        for data_elem in _iter_music_data_elements(root):
            word_id = None
            if data_elem.get("word_id"):
                try:
                    word_id = int(data_elem.get("word_id"))
                except ValueError:
                    pass

            word_id_elem = data_elem.find("word_id")
            if word_id is None and word_id_elem is not None and word_id_elem.text:
                word_id = int(word_id_elem.text.strip())

            if word_id is None:
                continue

            text = _extract_text_field(
                data_elem,
                [
                    "word", "word_string", "string", "str", "name",
                    "text", "word_name", "data",
                ],
            )
            if not text:
                best = ""
                for child in data_elem:
                    if child.tag.lower() == "word_id" or not child.text:
                        continue
                    candidate = decode_name_string(child.text) or child.text.strip()
                    if len(candidate) > len(best):
                        best = candidate
                text = best

            if text:
                word_dict[word_id] = text
    except Exception:
        pass

    return word_dict


def _iter_music_data_elements(root: ET.Element) -> List[ET.Element]:
    """兼容不同版本的 music_info / word_info XML 结构"""
    body = root.find("body")
    if body is not None:
        elems = body.findall("data")
        if elems:
            return elems

    elems = root.findall("data")
    if elems:
        return elems

    return root.findall(".//data")


def load_music_info(music_info_path: Path, word_dict: Optional[dict] = None) -> dict:
    """解析 music_info.xml，返回 {music_id: {name, bpm, levels, ...}}

    支持的曲名字段（按优先级）:
    - title_name: 可读曲名（部分版本XML包含）
    - name_string: 日文曲名 (Shift-JIS hex，含汉字)
    - ascii_name: 片假名读音名 (Shift-JIS hex)
    - word_id 引用: 通过 word_info 词库解析
    """
    info = {}
    if not music_info_path.exists():
        return info

    word_dict = word_dict or {}
    root = _parse_xml_root(music_info_path)

    for data_elem in _iter_music_data_elements(root):
        music_id_elem = data_elem.find("music_id")
        if music_id_elem is None:
            continue
        music_id = int(music_id_elem.text)

        info_elem = data_elem.find("info")
        lookup_elem = info_elem if info_elem is not None else data_elem

        title_name = _extract_text_field(lookup_elem, ["title_name"])
        if not title_name and word_dict:
            title_name = _resolve_word_id(
                lookup_elem,
                [
                    "title_name_id", "title_id", "name_id", "name_string_id",
                    "sub_title_name_id", "sub_name_string_id", "word_id",
                ],
                word_dict,
            )

        copyright_elem = data_elem.find("copyright_name")
        copyright_name = copyright_elem.text.strip() if copyright_elem is not None and copyright_elem.text else ""

        ascii_name = _extract_text_field(data_elem, ["ascii_name", "name_ascii", "reading_name"])
        japanese_name = _extract_text_field(
            data_elem, ["name_string", "japanese_name", "sub_name_string"]
        )
        reading_name = ""
        if japanese_name and _is_katakana_dominant(japanese_name):
            reading_name = japanese_name
            japanese_name = ""

        artist_name = _extract_text_field(
            lookup_elem, ["artist_name", "artist_string", "sub_artist_name"]
        )
        if not artist_name and word_dict:
            artist_name = _resolve_word_id(
                lookup_elem,
                [
                    "artist_name_id", "artist_id", "artist_word_id",
                    "sub_artist_name_id",
                ],
                word_dict,
            )

        if word_dict:
            scanned_title, scanned_artist = _resolve_ids_from_word_dict(data_elem, word_dict)
            title_name = title_name or scanned_title
            artist_name = artist_name or scanned_artist

        entry = {
            "title_name": title_name,
            "japanese_name": japanese_name,
            "reading_name": reading_name,
            "ascii_name": ascii_name,
            "copyright_name": copyright_name,
            "artist_name": artist_name,
        }
        name = resolve_display_title(entry) or f"unknown_{music_id}"

        bpm_min, bpm_max = _parse_bpm_fields(
            data_elem.find("bpm_min"), data_elem.find("bpm_max")
        )

        levels = {}
        for diff in ["bsc", "adv", "ext"]:
            lev_elem = data_elem.find(f"level_{diff}")
            detail_elem = data_elem.find(f"detail_level_{diff}")
            if lev_elem is not None and lev_elem.text:
                level_val = _parse_xml_float(lev_elem)
                detail_val = _parse_xml_float(detail_elem, level_val)
                levels[diff] = {
                    "level": int(level_val),
                    "detail": detail_val,
                }

        info[music_id] = {
            "name": name,
            "title_name": title_name,
            "japanese_name": japanese_name,
            "reading_name": reading_name,
            "ascii_name": ascii_name,
            "copyright_name": copyright_name,
            "artist_name": artist_name,
            "artist": artist_name,
            "bpm_min": bpm_min,
            "bpm_max": bpm_max,
            "levels": levels,
        }

    return info


def load_word_info(word_info_path: Path) -> dict:
    """解析 word_info.xml，返回 {music_id: {title, artist, ...}}

    word_info.xml 包含多语言文本信息，可能包含比 music_info.xml 更完整的曲名。
    """
    info = {}
    if not word_info_path.exists():
        return info

    try:
        root = _parse_xml_root(word_info_path)

        for data_elem in _iter_music_data_elements(root):
            music_id_elem = data_elem.find("music_id")
            if music_id_elem is None or not music_id_elem.text:
                continue
            music_id = int(music_id_elem.text)

            title = ""
            artist = ""
            for child in data_elem:
                tag = child.tag.lower()
                text = (child.text or "").strip()
                if not text:
                    continue
                if not title and (
                    tag in ("title_name", "word_name", "name", "title")
                    or ("title" in tag and "name" in tag)
                    or tag.endswith("_name") and "artist" not in tag and "copyright" not in tag
                ):
                    title = decode_name_string(text) or text
                elif not artist and (
                    tag in ("artist_name", "artist")
                    or ("artist" in tag and "name" in tag)
                ):
                    artist = decode_name_string(text) or text

            if title or artist:
                info[music_id] = {"title": title, "artist": artist}
    except Exception:
        pass

    return info


def _convert_song_audio(
    song_dir: Path,
    extracted: List[str],
    on_audio_progress: Optional[Callable[[float], None]] = None,
) -> None:
    """将解包出的 bgm .bin 转为标准 WAV（Beyond Ave 多为 bgm_1.bin）。

    idx.bin 为较短的游戏内预览/同步片段，Malody 谱面只需完整 bgm，故不转换 idx。
    """
    bgm_bins: list[Path] = []

    for filename in extracted:
        lower = filename.lower()
        path = song_dir / filename
        if not path.is_file():
            continue
        if lower.startswith("bgm") and lower.endswith(".bin"):
            bgm_bins.append(path)

    primary_bgm: Optional[Path] = None
    for preferred in ("bgm.bin", "bgm_1.bin"):
        candidate = song_dir / preferred
        if candidate in bgm_bins:
            primary_bgm = candidate
            break
    if primary_bgm is None and bgm_bins:
        bgm_bins.sort(key=lambda p: (len(p.name), -p.stat().st_size))
        primary_bgm = bgm_bins[0]

    if primary_bgm:
        convert_bmp_to_wav(primary_bgm, song_dir / "bgm.wav", on_progress=on_audio_progress)


def convert_bmp_to_wav(
    bmp_path: Path,
    wav_path: Path,
    on_progress: Optional[Callable[[float], None]] = None,
) -> bool:
    """将 Konami BMP (OKI4S ADPCM) 转换为标准 WAV"""
    from .konami_bmp import convert_bmp_file

    return convert_bmp_file(bmp_path, wav_path, on_progress)


REMOVED_SONG_STATUS = "版权到期"
REMOVED_SONG_HINT = "该曲版权已到期，本地无可用资源文件，无法提取"


def is_ifs_content_removed(ifs_path: Path) -> bool:
    """检查 IFS 是否为版权到期后的占位包（manifest 含 dummy_Edat，无实际谱面/音频）。"""
    if not HAS_IFSTOOLS:
        return False
    try:
        ifs = ifstools.IFS(str(ifs_path))
        xml_str = ifs.manifest.to_text()
        ifs.close()
        return "dummy_Edat" in xml_str
    except Exception:
        return False


# 旧名保留，避免外部脚本引用断裂
is_ifs_encrypted = is_ifs_content_removed


def _safe_folder_name(name: str) -> str:
    """保留日文/中文全名，仅去除 Windows 非法路径字符"""
    invalid = '<>:"/\\|?*'
    cleaned = "".join(c if c not in invalid else "_" for c in name)
    cleaned = cleaned.strip(" .")
    return cleaned or "unknown"


def _folder_display_name(song_info: dict) -> str:
    """解包目录名使用的曲名（优先日文汉字正式名）"""
    return (
        song_info.get("japanese_name")
        or resolve_display_title(song_info)
        or song_info.get("name")
        or "unknown"
    )


def _unique_dest_path(output_dir: Path, src: Path, ifs_subdir: Path) -> Path:
    """为解包文件生成不冲突的目标路径（避免曲绘 PNG 被覆盖后删除）"""
    dest = output_dir / src.name
    if not dest.exists():
        return dest

    parent_tag = src.parent.name if src.parent != ifs_subdir else ""
    if parent_tag:
        dest = output_dir / f"{parent_tag}_{src.name}"
        if not dest.exists():
            return dest

    for i in range(1, 200):
        dest = output_dir / f"{src.stem}_{i}{src.suffix}"
        if not dest.exists():
            return dest
    return output_dir / f"{src.stem}_{src.stat().st_size}{src.suffix}"


def extract_ifs(
    ifs_path: Path,
    output_dir: Path,
    *,
    tex_only: bool = False,
    dump_canvas: bool = False,
    rename_dupes: bool = True,
    flatten: bool = True,
) -> list:
    """使用 ifstools 解包 IFS 文件，返回提取的文件名列表

    曲绘 IFS (_jkt.ifs) 需设置 tex_only=True, dump_canvas=True 才能导出完整封面画布。
    """
    if not HAS_IFSTOOLS:
        raise RuntimeError("ifstools 未安装，无法解包 IFS 文件")

    ifs = ifstools.IFS(str(ifs_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    ifs.extract(
        path=str(output_dir),
        progress=False,
        tex_only=tex_only,
        dump_canvas=dump_canvas,
        rename_dupes=rename_dupes,
    )

    extracted_names: List[str] = []

    if not flatten:
        extracted_names = [f.name for f in ifs.tree.all_files]
        ifs.close()
        return extracted_names

    # ifstools 会在 output_dir 下创建子目录，需要递归移出所有文件
    ifs_subdir = output_dir / (ifs_path.stem + "_ifs")
    search_roots = [ifs_subdir] if ifs_subdir.exists() else [output_dir]
    moved = set()

    for search_root in search_roots:
        if not search_root.exists():
            continue
        for f in sorted(search_root.rglob("*")):
            if not f.is_file():
                continue
            dest = _unique_dest_path(output_dir, f, search_root)
            if dest.resolve() in moved:
                continue
            shutil.move(str(f), str(dest))
            extracted_names.append(dest.name)
            moved.add(dest.resolve())

    if ifs_subdir.exists() and ifs_subdir.is_dir():
        shutil.rmtree(ifs_subdir, ignore_errors=True)

    if not extracted_names:
        extracted_names = [f.name for f in output_dir.iterdir() if f.is_file()]

    ifs.close()
    return extracted_names


def _find_jacket_resource(
    music_id: int,
    ifs_dir: Path,
    msc_ifs_path: Optional[Path] = None,
    jacket_index: Optional[dict[int, Path]] = None,
) -> Optional[Path]:
    """查找与 music_id 对应的封面资源（优先索引 / 同目录，不做全树 rglob）"""
    if jacket_index and music_id in jacket_index:
        return jacket_index[music_id]

    id_str = str(music_id)
    exact_names = [
        f"{id_str}_jkt.ifs",
        f"{id_str}_jkt.bin",
        f"{id_str}_ifs.ifs",
    ]

    local_dirs: List[Path] = []
    if msc_ifs_path is not None:
        local_dirs.append(msc_ifs_path.parent)
    if ifs_dir not in local_dirs:
        local_dirs.append(ifs_dir)

    for parent in local_dirs:
        for name in exact_names:
            candidate = parent / name
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() == ".ifs" and is_ifs_content_removed(candidate):
                return None
            return candidate

    return None


def _extract_jacket_image(
    jacket_path: Path, song_dir: Path, music_id: int
) -> Tuple[bool, str]:
    """从封面资源 (_jkt.ifs / texbin .bin) 提取曲绘，返回 (是否成功, 文件名)"""
    from .texbin_extractor import extract_texbin_png

    if jacket_path.suffix.lower() == ".bin" and "bnr" in jacket_path.name.lower():
        png_data = extract_texbin_png(jacket_path, music_id=music_id)
        if png_data:
            from .jacket_fixup import fix_arcade_jacket_colors

            jacket_filename = f"jkt_{music_id}.png"
            dest = song_dir / jacket_filename
            dest.write_bytes(png_data)
            fix_arcade_jacket_colors(dest)
            return True, jacket_filename
        return False, ""

    jkt_temp = song_dir / "_jkt_temp"
    try:
        if jacket_path.suffix.lower() == ".bin":
            try:
                extract_ifs(jacket_path, jkt_temp, tex_only=True, dump_canvas=True)
            except Exception:
                return False, ""
        else:
            extract_ifs(
                jacket_path, jkt_temp,
                tex_only=True, dump_canvas=True, rename_dupes=True,
            )

        jkt_images = _find_images_in_dir(jkt_temp)
        best_jkt = _pick_best_jacket(jkt_images, music_id)
        if not best_jkt:
            return False, ""

        from .jacket_fixup import fix_arcade_jacket_colors

        jacket_filename = f"jkt_{music_id}{best_jkt.suffix.lower()}"
        dest = song_dir / jacket_filename
        shutil.copy2(best_jkt, dest)
        fix_arcade_jacket_colors(dest)
        return True, jacket_filename
    except Exception:
        return False, ""
    finally:
        if jkt_temp.exists():
            shutil.rmtree(jkt_temp, ignore_errors=True)


def _extract_nested_jacket_ifs(song_dir: Path, music_id: int) -> Tuple[bool, str]:
    """解包歌曲目录内嵌套的 _jkt*.ifs 并提取曲绘"""
    for nested_ifs in sorted(song_dir.rglob("*jkt*.ifs")):
        ok, filename = _extract_jacket_image(nested_ifs, song_dir, music_id)
        if ok:
            return ok, filename
    return False, ""


def _finalize_song_info(
    song_info: dict, music_id: int, word_info: Optional[dict] = None
) -> dict:
    """合并 word_info / 参考曲名库，并重新计算最终曲名与曲师"""
    from .song_database import get_song_artist, load_reference_tsv

    load_reference_tsv()
    info = dict(song_info)

    if word_info and music_id in word_info:
        wi = word_info[music_id]
        if wi.get("title"):
            if not info.get("title_name"):
                info["title_name"] = wi["title"]
            current_name = info.get("name", "")
            if not current_name or str(current_name).startswith("unknown_"):
                info["name"] = wi["title"]
        if wi.get("artist"):
            info["artist"] = wi["artist"]
            info["artist_name"] = wi["artist"]

    from .metadata_sources import load_user_metadata_tsv, lookup_atwiki_by_levels
    from .song_database import get_reference_song_artist, get_reference_song_name

    user_titles, user_artists = load_user_metadata_tsv()
    if music_id in user_titles:
        info["title_name"] = user_titles[music_id]

    name = resolve_display_title(info)
    ref_name = get_reference_song_name(music_id)
    if ref_name and (
        not name
        or str(name).startswith("unknown_")
        or _is_katakana_dominant(name)
        or name == info.get("reading_name")
    ):
        name = ref_name

    if (not name or _is_katakana_dominant(name) or str(name).startswith("unknown_")):
        atwiki = lookup_atwiki_by_levels(info)
        if atwiki:
            name = atwiki[0]
            if not resolve_artist(info) and atwiki[1]:
                info["artist"] = atwiki[1]
                info["artist_name"] = atwiki[1]

    info["name"] = name or f"unknown_{music_id}"

    artist = resolve_artist(info)
    if not artist:
        artist = get_reference_song_artist(music_id) or user_artists.get(music_id, "")
    if not artist:
        atwiki = lookup_atwiki_by_levels(info)
        if atwiki and atwiki[1]:
            artist = atwiki[1]
    if artist:
        info["artist"] = artist
        info["artist_name"] = artist

    return info


def _is_prior_unpack_jacket(path: Path, music_id: int) -> bool:
    """是否为上次解包写入的 jkt_{id}*.png，避免重复解包时误当作 IFS 内纹理。"""
    name = path.name.lower()
    prefix = f"jkt_{music_id}".lower()
    if not name.startswith(prefix):
        return False
    suffix = path.suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg"):
        return False
    rest = name[len(prefix) : -len(suffix)]
    return rest == "" or rest.startswith("_")


def _find_images_in_dir(
    directory: Path, *, exclude_music_id: Optional[int] = None
) -> List[Path]:
    """在目录及子目录中查找所有图片文件"""
    images = []
    try:
        for f in directory.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            if exclude_music_id is not None and _is_prior_unpack_jacket(
                f, exclude_music_id
            ):
                continue
            images.append(f)
    except OSError:
        pass
    return images


def _pick_best_jacket(images: List[Path], music_id: int) -> Optional[Path]:
    """从候选图片中选择最合适的封面图

    优先级: _canvas_ 完整画布 > jkt/jacket/cover + id > 最大正方形图
    """
    if not images:
        return None

    id_str = str(music_id)

    canvas_images = [img for img in images if "_canvas_" in img.name.lower()]
    if canvas_images:
        try:
            return max(canvas_images, key=lambda p: p.stat().st_size)
        except OSError:
            return canvas_images[0]

    for img in images:
        name_lower = img.name.lower()
        if any(kw in name_lower for kw in ("jkt", "jacket", "cover")) and id_str in name_lower:
            return img

    for img in images:
        name_lower = img.name.lower()
        if any(kw in name_lower for kw in ("jkt", "jacket", "cover", "artwork")):
            return img

    try:
        return max(images, key=lambda p: p.stat().st_size)
    except (OSError, ValueError):
        return images[0]


def extract_song(ifs_path: Path, music_info: dict, output_base: Path,
                 ifs_dir: Path = None, word_info: dict = None,
                 jacket_index: Optional[dict[int, Path]] = None,
                 progress: Optional[ProgressReporter] = None) -> Optional[Path]:
    """
    解包单个乐曲 IFS，返回输出目录路径。
    提取谱面 (.eve)、转换音频 (bgm.bin → .wav)、提取封面图片、写入 song_info.txt。

    Args:
        ifs_path: IFS 文件路径
        music_info: load_music_info() 返回的元数据字典
        output_base: 输出根目录
        ifs_dir: IFS 文件所在目录（用于查找封面 IFS），默认与 ifs_path 同目录
        word_info: load_word_info() 返回的补充文本信息（曲名/艺术家）
    """
    if ifs_dir is None:
        ifs_dir = ifs_path.parent

    if is_ifs_content_removed(ifs_path):
        return None

    def report(message: str, percent: int) -> None:
        if progress:
            progress(message, percent)

    music_id = _parse_music_id_from_ifs(ifs_path)

    song_info = _finalize_song_info(
        music_info.get(music_id, {}), music_id, word_info
    )
    song_name = song_info["name"]
    folder_title = _safe_folder_name(_folder_display_name(song_info))
    song_dir = output_base / f"{music_id}_{folder_title}"
    song_dir.mkdir(parents=True, exist_ok=True)

    report("解包 IFS 容器...", 5)
    extracted = extract_ifs(ifs_path, song_dir)
    if not extracted:
        return None

    report("转换 BGM 音频 (ADPCM → WAV)...", 20)

    def audio_progress(frac: float) -> None:
        report("转换 BGM 音频...", 20 + int(frac * 60))

    _convert_song_audio(song_dir, extracted, on_audio_progress=audio_progress)

    report("提取曲绘...", 85)
    jacket_copied = False
    jacket_filename = ""

    jacket_path = _find_jacket_resource(
        music_id, ifs_dir, msc_ifs_path=ifs_path, jacket_index=jacket_index,
    )
    if jacket_path:
        jacket_copied, jacket_filename = _extract_jacket_image(
            jacket_path, song_dir, music_id
        )

    # 2. _msc.ifs 解包后自带的纹理图（排除上次解包留下的 jkt_{id}*.png）
    if not jacket_copied:
        images = _find_images_in_dir(song_dir, exclude_music_id=music_id)
        best_jacket = _pick_best_jacket(images, music_id)
        if best_jacket:
            from .jacket_fixup import fix_arcade_jacket_colors

            jacket_filename = f"jkt_{music_id}{best_jacket.suffix.lower()}"
            dest = song_dir / jacket_filename
            if best_jacket.resolve() != dest.resolve():
                shutil.copy2(best_jacket, dest)
            fix_arcade_jacket_colors(dest)
            jacket_copied = True

    # 3. 解包目录内嵌套的 _jkt*.ifs
    if not jacket_copied:
        jacket_copied, jacket_filename = _extract_nested_jacket_ifs(song_dir, music_id)

    # 4. eagate / zetaraku 曲绘回退
    if not jacket_copied:
        from .jacket_fallback import fetch_jacket_fallback

        jacket_copied, jacket_filename = fetch_jacket_fallback(
            song_dir, song_info, music_id=music_id,
        )

    if resolve_bpm(song_info) <= 0:
        eve_bpm = _parse_bpm_from_eve(song_dir)
        if eve_bpm > 0:
            song_info["bpm_max"] = eve_bpm
            song_info["bpm_min"] = eve_bpm

    report("写入歌曲信息...", 95)
    info_path = song_dir / "song_info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"Music ID: {music_id}\n")
        f.write(f"Name: {song_name}\n")
        title_name = song_info.get("title_name", "")
        if title_name and title_name != song_name:
            f.write(f"Title Name: {title_name}\n")
        japanese_name = song_info.get("japanese_name", "")
        if japanese_name and japanese_name != song_name:
            f.write(f"Japanese Name: {japanese_name}\n")
        ascii_name_val = song_info.get("ascii_name", "")
        if ascii_name_val and ascii_name_val != song_name:
            f.write(f"ASCII Name: {ascii_name_val}\n")
        artist = resolve_artist(song_info) or song_info.get("artist", "")
        if artist:
            f.write(f"Artist: {artist}\n")
        reading_name = song_info.get("reading_name", "")
        if reading_name and reading_name != song_name:
            f.write(f"Reading Name: {reading_name}\n")
        bpm = resolve_bpm(song_info)
        if bpm > 0:
            bpm_min = song_info.get("bpm_min", 0)
            bpm_max = song_info.get("bpm_max", 0)
            if bpm_min and bpm_max and bpm_min != bpm_max and bpm_min > 0:
                f.write(f"BPM (ref): {bpm_min}-{bpm_max}\n")
            else:
                f.write(f"BPM (ref): {bpm}\n")
        for diff, lev in song_info.get("levels", {}).items():
            f.write(f"Level {diff.upper()}: {lev['level']} ({lev['detail']})\n")
        if jacket_copied and jacket_filename:
            f.write(f"Jacket: {jacket_filename}\n")
            f.write("JacketColorFix: swap_rb\n")
        f.write(f"\nFiles:\n")
        for filename in extracted:
            f.write(f"  {filename}\n")

    report("完成", 100)
    return song_dir
