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
from typing import Optional, List

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

    # 可能本身就是明文（含日文/中文/ASCII）
    if any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or c.isascii() for c in encoded):
        return encoded

    return encoded


def load_music_info(music_info_path: Path) -> dict:
    """解析 music_info.xml，返回 {music_id: {name, bpm, levels, ...}}

    支持的曲名字段（按优先级）:
    - title_name: 可读曲名（部分版本XML包含）
    - ascii_name: 罗马音/英文曲名 (Shift-JIS hex)
    - name_string: 日文曲名 (Shift-JIS hex)
    - copyright_name: 版权信息中的曲名
    """
    info = {}
    if not music_info_path.exists():
        return info

    tree = ET.parse(music_info_path)
    root = tree.getroot()
    body = root.find("body")
    if body is None:
        return info

    for data_elem in body.findall("data"):
        music_id_elem = data_elem.find("music_id")
        if music_id_elem is None:
            continue
        music_id = int(music_id_elem.text)

        # 收集所有可能的曲名来源
        title_name_elem = data_elem.find("title_name")
        title_name = title_name_elem.text.strip() if title_name_elem is not None and title_name_elem.text else ""

        copyright_elem = data_elem.find("copyright_name")
        copyright_name = copyright_elem.text.strip() if copyright_elem is not None and copyright_elem.text else ""

        ascii_elem = data_elem.find("ascii_name")
        ascii_name = decode_name_string(ascii_elem.text) if ascii_elem is not None and ascii_elem.text else ""

        name_elem = data_elem.find("name_string")
        japanese_name = decode_name_string(name_elem.text) if name_elem is not None and name_elem.text else ""

        # 曲名优先级: title_name > ascii_name > japanese_name > copyright_name
        name = title_name or ascii_name or japanese_name or copyright_name or f"unknown_{music_id}"

        bpm_min_elem = data_elem.find("bpm_min")
        bpm_max_elem = data_elem.find("bpm_max")
        bpm_min_raw = int(bpm_min_elem.text) if bpm_min_elem is not None and bpm_min_elem.text else 0
        bpm_max_raw = int(bpm_max_elem.text) if bpm_max_elem is not None and bpm_max_elem.text else 0

        if bpm_max_raw > 1000:
            bpm_min = round(60_000_000 / bpm_min_raw, 2) if bpm_min_raw > 0 else 0
            bpm_max = round(60_000_000 / bpm_max_raw, 2) if bpm_max_raw > 0 else 0
        else:
            bpm_min = float(bpm_min_raw)
            bpm_max = float(bpm_max_raw)

        levels = {}
        for diff in ["bsc", "adv", "ext"]:
            lev_elem = data_elem.find(f"level_{diff}")
            detail_elem = data_elem.find(f"detail_level_{diff}")
            if lev_elem is not None:
                levels[diff] = {
                    "level": int(lev_elem.text),
                    "detail": float(detail_elem.text) if detail_elem is not None else int(lev_elem.text)
                }

        info[music_id] = {
            "name": name,
            "title_name": title_name,
            "japanese_name": japanese_name,
            "ascii_name": ascii_name,
            "copyright_name": copyright_name,
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
        body = root.find("body")
        if body is None:
            return info

        for data_elem in body.findall("data"):
            music_id_elem = data_elem.find("music_id")
            if music_id_elem is None:
                continue
            music_id = int(music_id_elem.text)

            title = ""
            artist = ""
            for child in data_elem:
                tag = child.tag
                text = (child.text or "").strip()
                if not text:
                    continue
                if "title" in tag.lower() and "name" in tag.lower():
                    title = text
                elif "artist" in tag.lower() and "name" in tag.lower():
                    artist = text

            if title:
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
        return True


def extract_ifs(ifs_path: Path, output_dir: Path) -> list:
    """使用 ifstools 解包 IFS 文件，返回提取的文件名列表"""
    if not HAS_IFSTOOLS:
        raise RuntimeError("ifstools 未安装，无法解包 IFS 文件")

    ifs = ifstools.IFS(str(ifs_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    ifs.extract(path=str(output_dir), progress=False)

    extracted = [f.name for f in ifs.tree.all_files]

    # ifstools 会在 output_dir 下创建子目录，需要移出来
    ifs_subdir = output_dir / (ifs_path.stem + "_ifs")
    if ifs_subdir.exists() and ifs_subdir.is_dir():
        for f in ifs_subdir.iterdir():
            dest = output_dir / f.name
            if not dest.exists():
                f.rename(dest)
        try:
            ifs_subdir.rmdir()
        except OSError:
            pass

    ifs.close()
    return extracted


def _find_jacket_ifs(music_id: int, ifs_dir: Path) -> Optional[Path]:
    """查找与 music_id 对应的封面 IFS 文件

    Jubeat 封面图可能存储在: {id}_jkt.ifs, {id}_ifs.ifs
    或子目录 d{X}/ 下的同名文件
    """
    candidates = [
        ifs_dir / f"{music_id}_jkt.ifs",
        ifs_dir / f"{music_id}_ifs.ifs",
    ]
    # 搜索子目录 (ifs_pack/d{X}/ 结构)
    for subdir in ifs_dir.iterdir():
        if subdir.is_dir():
            candidates.extend([
                subdir / f"{music_id}_jkt.ifs",
                subdir / f"{music_id}_ifs.ifs",
            ])

    for candidate in candidates:
        if candidate.exists() and not is_ifs_encrypted(candidate):
            return candidate
    return None


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
                 ifs_dir: Path = None) -> Optional[Path]:
    """
    解包单个乐曲 IFS，返回输出目录路径。
    提取谱面 (.eve)、转换音频 (bgm.bin → .wav)、提取封面图片、写入 song_info.txt。

    Args:
        ifs_path: IFS 文件路径
        music_info: load_music_info() 返回的元数据字典
        output_base: 输出根目录
        ifs_dir: IFS 文件所在目录（用于查找封面 IFS），默认与 ifs_path 同目录
    """
    if ifs_dir is None:
        ifs_dir = ifs_path.parent

    stem = ifs_path.stem
    music_id_str = stem.replace("_msc", "")
    try:
        music_id = int(music_id_str)
    except ValueError:
        music_id = 0

    song_info = music_info.get(music_id, {})
    song_name = song_info.get("name", f"unknown_{music_id}")
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in song_name)

    song_dir = output_base / f"{music_id}_{safe_name}"
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

    # 1. 查找 _msc.ifs 解包后已有的图片 (ifstools 自动转换纹理为 PNG)
    images = _find_images_in_dir(song_dir)
    best_jacket = _pick_best_jacket(images, music_id)
    if best_jacket:
        dest = song_dir / f"jkt_{music_id}{best_jacket.suffix.lower()}"
        if best_jacket != dest:
            shutil.copy2(best_jacket, dest)
        jacket_copied = True

    # 2. 查找并解包封面专用 IFS (_jkt.ifs / _ifs.ifs)
    if not jacket_copied:
        jkt_ifs = _find_jacket_ifs(music_id, ifs_dir)
        if jkt_ifs:
            jkt_temp = song_dir / "_jkt_temp"
            try:
                extract_ifs(jkt_ifs, jkt_temp)
                jkt_images = _find_images_in_dir(jkt_temp)
                best_jkt = _pick_best_jacket(jkt_images, music_id)
                if best_jkt:
                    dest = song_dir / f"jkt_{music_id}{best_jkt.suffix.lower()}"
                    shutil.copy2(best_jkt, dest)
                    jacket_copied = True
            except Exception:
                pass
            finally:
                if jkt_temp.exists():
                    shutil.rmtree(jkt_temp, ignore_errors=True)

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
        bpm_min = song_info.get("bpm_min", 0)
        bpm_max = song_info.get("bpm_max", 0)
        if bpm_min and bpm_min != bpm_max:
            f.write(f"BPM (ref): {bpm_min}-{bpm_max}\n")
        else:
            f.write(f"BPM (ref): {bpm_max}\n")
        for diff, lev in song_info.get("levels", {}).items():
            f.write(f"Level {diff.upper()}: {lev['level']} ({lev['detail']})\n")
        if jacket_copied:
            f.write(f"Jacket: jkt_{music_id}.png\n")
        f.write(f"\nFiles:\n")
        for filename in extracted:
            f.write(f"  {filename}\n")

    return song_dir
