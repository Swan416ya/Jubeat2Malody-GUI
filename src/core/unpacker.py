"""
Jubeat IFS 解包模块

从 Jubeat 游戏文件中提取谱面 (EVE)、音频 (BGM)、封面图片和元数据。
依赖: ifstools (IFS 解包), 标准库 (BMP→WAV, music_info.xml 解析)
"""

import os
import re
import struct
import wave
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, List, Tuple

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


def find_metadata_xml(root: Path, filename: str) -> Optional[Path]:
    """在 Jubeat 数据目录中查找 music_info.xml / word_info.xml

    常见路径:
    - {root}/music_info.xml
    - {root}/music_info/music_info.xml
    - {root}/word_info/word_info.xml
    - 任意子目录中的同名文件 (rglob)
    """
    if not root.exists():
        return None

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

    兼容两种格式:
    - 微秒/拍 (如 3000000) → 转换为标准 BPM
    - 直接 BPM 值 (如 139.5)
    """
    bpm_min_raw = _parse_xml_float(bpm_min_elem)
    bpm_max_raw = _parse_xml_float(bpm_max_elem)

    if bpm_max_raw > 1000:
        bpm_min = round(60_000_000 / bpm_min_raw, 2) if bpm_min_raw > 0 else 0.0
        bpm_max = round(60_000_000 / bpm_max_raw, 2) if bpm_max_raw > 0 else 0.0
    else:
        bpm_min = bpm_min_raw
        bpm_max = bpm_max_raw

    return bpm_min, bpm_max


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
    """选择最适合显示的曲名（优先汉字/假名混合名，避免片假名读音）"""
    candidates = [
        info.get("japanese_name"),
        info.get("title_name"),
        info.get("name"),
        info.get("ascii_name"),
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
    """选择艺术家名（copyright_name 是版权方，不是曲师）"""
    for key in ("artist", "artist_name"):
        value = (info.get(key) or "").strip()
        if value and value.upper() not in ("KONAMI", "KONAMI AMUSEMENT", "COPYRIGHT"):
            return value
    return ""


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


def load_word_dictionary(word_info_path: Path) -> dict:
    """解析 word_info.xml 中的全局词库 {word_id: text}"""
    word_dict = {}
    if not word_info_path.exists():
        return word_dict

    try:
        tree = ET.parse(word_info_path)
        root = tree.getroot()
        for data_elem in _iter_music_data_elements(root):
            word_id_elem = data_elem.find("word_id")
            if word_id_elem is None or not word_id_elem.text:
                continue
            word_id = int(word_id_elem.text.strip())
            text = _extract_text_field(
                data_elem, ["word", "word_string", "name", "text", "word_name"]
            )
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
    tree = ET.parse(music_info_path)
    root = tree.getroot()

    for data_elem in _iter_music_data_elements(root):
        music_id_elem = data_elem.find("music_id")
        if music_id_elem is None:
            continue
        music_id = int(music_id_elem.text)

        title_name = _extract_text_field(data_elem, ["title_name"])
        if not title_name and word_dict:
            title_name = _resolve_word_id(
                data_elem,
                ["title_name_id", "title_id", "name_id", "word_id"],
                word_dict,
            )

        copyright_elem = data_elem.find("copyright_name")
        copyright_name = copyright_elem.text.strip() if copyright_elem is not None and copyright_elem.text else ""

        ascii_name = _extract_text_field(data_elem, ["ascii_name"])
        japanese_name = _extract_text_field(data_elem, ["name_string", "japanese_name"])

        artist_name = _extract_text_field(data_elem, ["artist_name", "artist_string"])
        if not artist_name and word_dict:
            artist_name = _resolve_word_id(
                data_elem,
                ["artist_name_id", "artist_id", "artist_word_id"],
                word_dict,
            )

        entry = {
            "title_name": title_name,
            "japanese_name": japanese_name,
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
        tree = ET.parse(word_info_path)
        root = tree.getroot()

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


def convert_bmp_to_wav(bmp_path: Path, wav_path: Path) -> bool:
    """将 Konami BMP 格式音频转换为标准 WAV"""
    try:
        with open(bmp_path, "rb") as f:
            data = f.read()

        if len(data) < 32 or data[:4] != b"BMP\x00":
            return False

        data_size = struct.unpack(">I", data[4:8])[0]
        channels = struct.unpack(">H", data[16:18])[0]
        bits = struct.unpack(">H", data[18:20])[0]
        sample_rate = struct.unpack(">I", data[20:24])[0]

        if channels not in (1, 2) or bits != 16 or sample_rate == 0:
            channels = struct.unpack("<H", data[16:18])[0]
            bits = struct.unpack("<H", data[18:20])[0]
            sample_rate = struct.unpack(">I", data[20:24])[0]

        if channels not in (1, 2) or bits != 16 or sample_rate == 0:
            return False

        pcm_data = data[32:]

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(bits // 8)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_data)

        return True
    except Exception:
        return False


def is_ifs_encrypted(ifs_path: Path) -> bool:
    """检查 IFS 文件是否加密 (dummy_Edat)"""
    if not HAS_IFSTOOLS:
        return False
    try:
        ifs = ifstools.IFS(str(ifs_path))
        xml_str = ifs.manifest.to_text()
        ifs.close()
        return "dummy_Edat" in xml_str
    except Exception:
        return False


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


def extract_ifs(ifs_path: Path, output_dir: Path) -> list:
    """使用 ifstools 解包 IFS 文件，返回提取的文件名列表"""
    if not HAS_IFSTOOLS:
        raise RuntimeError("ifstools 未安装，无法解包 IFS 文件")

    ifs = ifstools.IFS(str(ifs_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    ifs.extract(path=str(output_dir), progress=False)

    extracted_names: List[str] = []

    # ifstools 会在 output_dir 下创建子目录，需要递归移出所有文件
    ifs_subdir = output_dir / (ifs_path.stem + "_ifs")
    if ifs_subdir.exists() and ifs_subdir.is_dir():
        for f in sorted(ifs_subdir.rglob("*")):
            if not f.is_file():
                continue
            dest = _unique_dest_path(output_dir, f, ifs_subdir)
            shutil.move(str(f), str(dest))
            extracted_names.append(dest.name)
        shutil.rmtree(ifs_subdir, ignore_errors=True)
    else:
        extracted_names = [f.name for f in output_dir.iterdir() if f.is_file()]

    ifs.close()
    return extracted_names


def _find_jacket_ifs(
    music_id: int, ifs_dir: Path, msc_ifs_path: Optional[Path] = None
) -> Optional[Path]:
    """查找与 music_id 对应的封面 IFS 文件

    Jubeat 封面图可能存储在: {id}_jkt.ifs, {id}_ifs.ifs
    优先在与 _msc.ifs 同目录查找，再递归搜索整个数据目录。
    """
    id_str = str(music_id)
    exact_names = [
        f"{id_str}_jkt.ifs",
        f"{id_str}_ifs.ifs",
    ]

    search_roots = []
    if msc_ifs_path is not None:
        search_roots.append(msc_ifs_path.parent)
    if ifs_dir not in search_roots:
        search_roots.append(ifs_dir)

    seen = set()

    def _accept(candidate: Path) -> Optional[Path]:
        key = str(candidate.resolve())
        if key in seen:
            return None
        seen.add(key)
        if candidate.is_file() and not is_ifs_encrypted(candidate):
            return candidate
        return None

    for root in search_roots:
        for name in exact_names:
            found = _accept(root / name)
            if found:
                return found

        for name in exact_names:
            for candidate in root.rglob(name):
                found = _accept(candidate)
                if found:
                    return found

        # 宽松匹配: *{music_id}*jkt*.ifs
        for candidate in root.rglob(f"*{id_str}*jkt*.ifs"):
            found = _accept(candidate)
            if found:
                return found

    return None


def _extract_jacket_image(
    jkt_ifs_path: Path, song_dir: Path, music_id: int
) -> Tuple[bool, str]:
    """从 _jkt.ifs 解包并提取曲绘到歌曲目录，返回 (是否成功, 文件名)"""
    jkt_temp = song_dir / "_jkt_temp"
    try:
        extract_ifs(jkt_ifs_path, jkt_temp)
        jkt_images = _find_images_in_dir(jkt_temp)
        best_jkt = _pick_best_jacket(jkt_images, music_id)
        if not best_jkt:
            return False, ""

        jacket_filename = f"jkt_{music_id}{best_jkt.suffix.lower()}"
        shutil.copy2(best_jkt, song_dir / jacket_filename)
        return True, jacket_filename
    except Exception:
        return False, ""
    finally:
        if jkt_temp.exists():
            shutil.rmtree(jkt_temp, ignore_errors=True)


def _finalize_song_info(
    song_info: dict, music_id: int, word_info: Optional[dict] = None
) -> dict:
    """合并 word_info / 本地曲名库，并重新计算最终曲名"""
    from .song_database import get_song_name

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

    name = resolve_display_title(info)
    if not name or str(name).startswith("unknown_"):
        db_name = get_song_name(music_id, local_db={music_id: info} if info else None)
        if db_name:
            name = db_name

    info["name"] = name or f"unknown_{music_id}"

    artist = resolve_artist(info)
    if artist:
        info["artist"] = artist

    return info


def _find_images_in_dir(directory: Path) -> List[Path]:
    """在目录及子目录中查找所有图片文件"""
    images = []
    try:
        for f in directory.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                images.append(f)
    except OSError:
        pass
    return images


def _pick_best_jacket(images: List[Path], music_id: int) -> Optional[Path]:
    """从候选图片中选择最合适的封面图

    优先级: jkt/jacket/cover + id > jkt/jacket/cover > 最大文件
    """
    if not images:
        return None

    id_str = str(music_id)
    for img in images:
        name_lower = img.name.lower()
        if any(kw in name_lower for kw in ("jkt", "jacket", "cover")) and id_str in name_lower:
            return img

    for img in images:
        name_lower = img.name.lower()
        if any(kw in name_lower for kw in ("jkt", "jacket", "cover")):
            return img

    try:
        return max(images, key=lambda p: p.stat().st_size)
    except (OSError, ValueError):
        return images[0]


def extract_song(ifs_path: Path, music_info: dict, output_base: Path,
                 ifs_dir: Path = None, word_info: dict = None) -> Optional[Path]:
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

    stem = ifs_path.stem
    music_id_str = stem.replace("_msc", "")
    try:
        music_id = int(music_id_str)
    except ValueError:
        music_id = 0

    song_info = _finalize_song_info(
        music_info.get(music_id, {}), music_id, word_info
    )
    song_name = song_info["name"]
    folder_title = _safe_folder_name(_folder_display_name(song_info))
    song_dir = output_base / f"{music_id}_{folder_title}"
    song_dir.mkdir(parents=True, exist_ok=True)

    extracted = extract_ifs(ifs_path, song_dir)
    if not extracted:
        return None

    # 转换音频
    for filename in extracted:
        file_path = song_dir / filename
        if filename == "bgm.bin":
            wav_path = song_dir / "bgm.wav"
            convert_bmp_to_wav(file_path, wav_path)
        elif filename == "idx.bin":
            wav_path = song_dir / "idx.wav"
            convert_bmp_to_wav(file_path, wav_path)

    # 提取封面图片
    jacket_copied = False
    jacket_filename = ""

    # 1. 查找 _msc.ifs 解包后已有的图片 (ifstools 自动转换纹理为 PNG)
    images = _find_images_in_dir(song_dir)
    best_jacket = _pick_best_jacket(images, music_id)
    if best_jacket:
        jacket_filename = f"jkt_{music_id}{best_jacket.suffix.lower()}"
        dest = song_dir / jacket_filename
        if best_jacket.resolve() != dest.resolve():
            shutil.copy2(best_jacket, dest)
        jacket_copied = True

    # 2. 查找并解包封面专用 IFS (_jkt.ifs)
    if not jacket_copied:
        jkt_ifs = _find_jacket_ifs(music_id, ifs_dir, msc_ifs_path=ifs_path)
        if jkt_ifs:
            jacket_copied, jacket_filename = _extract_jacket_image(
                jkt_ifs, song_dir, music_id
            )

    # 写入歌曲信息
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
        reading_name = song_info.get("ascii_name", "")
        if reading_name and reading_name != song_name:
            f.write(f"Reading Name: {reading_name}\n")
        bpm_min = song_info.get("bpm_min", 0)
        bpm_max = song_info.get("bpm_max", 0)
        if bpm_min and bpm_min != bpm_max:
            f.write(f"BPM (ref): {bpm_min}-{bpm_max}\n")
        else:
            f.write(f"BPM (ref): {bpm_max}\n")
        for diff, lev in song_info.get("levels", {}).items():
            f.write(f"Level {diff.upper()}: {lev['level']} ({lev['detail']})\n")
        if jacket_copied and jacket_filename:
            f.write(f"Jacket: {jacket_filename}\n")
        f.write(f"\nFiles:\n")
        for filename in extracted:
            f.write(f"  {filename}\n")

    return song_dir
