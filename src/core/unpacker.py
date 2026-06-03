"""
Jubeat IFS 解包模块

从 Jubeat 游戏文件中提取谱面 (EVE)、音频 (BGM) 和元数据。
依赖: ifstools (IFS 解包), 标准库 (BMP→WAV, music_info.xml 解析)
"""

import os
import struct
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

try:
    import ifstools
    HAS_IFSTOOLS = True
except ImportError:
    HAS_IFSTOOLS = False


def decode_name_string(encoded: str) -> str:
    """解码 music_info.xml 中的 name_string (Shift-JIS 编码的十六进制字符串)"""
    try:
        raw = bytes.fromhex(encoded)
        return raw.decode("shift_jis")
    except Exception:
        return encoded


def load_music_info(music_info_path: Path) -> dict:
    """解析 music_info.xml，返回 {music_id: {name, bpm, levels, ...}}"""
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

        # 优先使用 ascii_name（罗马音/英文），没有时用 name_string（日文原名）
        ascii_elem = data_elem.find("ascii_name")
        name_elem = data_elem.find("name_string")
        ascii_name = decode_name_string(ascii_elem.text) if ascii_elem is not None and ascii_elem.text else ""
        japanese_name = decode_name_string(name_elem.text) if name_elem is not None else ""
        # 显示名优先用 ascii，没有则用日文名
        name = ascii_name or japanese_name or f"unknown_{music_id}"

        bpm_min_elem = data_elem.find("bpm_min")
        bpm_max_elem = data_elem.find("bpm_max")
        # music_info.xml 中 BPM 可能是实际值或编码值
        # 先读取原始值，后续根据范围判断是否需要转换
        bpm_min_raw = int(bpm_min_elem.text) if bpm_min_elem is not None and bpm_min_elem.text else 0
        bpm_max_raw = int(bpm_max_elem.text) if bpm_max_elem is not None and bpm_max_elem.text else 0

        # 判断 BPM 编码方式：
        # 如果值 > 1000，很可能是微秒/拍编码 (value = 60,000,000 / BPM)
        # 如果值 <= 300，是实际 BPM 值
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
            "japanese_name": japanese_name,
            "ascii_name": ascii_name,
            "bpm_min": bpm_min,
            "bpm_max": bpm_max,
            "levels": levels,
        }

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


def extract_song(ifs_path: Path, music_info: dict, output_base: Path) -> Optional[Path]:
    """
    解包单个乐曲 IFS，返回输出目录路径。
    提取谱面 (.eve)、转换音频 (bgm.bin → .wav)、写入 song_info.txt。
    """
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

    # 写入歌曲信息
    info_path = song_dir / "song_info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"Music ID: {music_id}\n")
        f.write(f"Name: {song_name}\n")
        japanese_name = song_info.get("japanese_name", "")
        if japanese_name and japanese_name != song_name:
            f.write(f"Japanese Name: {japanese_name}\n")
        ascii_name_val = song_info.get("ascii_name", "")
        if ascii_name_val and ascii_name_val != song_name:
            f.write(f"ASCII Name: {ascii_name_val}\n")
        # XML 中的 BPM 只是参考值，实际 BPM 变化在谱面 TEMPO 事件中
        bpm_min = song_info.get("bpm_min", 0)
        bpm_max = song_info.get("bpm_max", 0)
        if bpm_min and bpm_min != bpm_max:
            f.write(f"BPM (ref): {bpm_min}-{bpm_max}\n")
        else:
            f.write(f"BPM (ref): {bpm_max}\n")
        for diff, lev in song_info.get("levels", {}).items():
            f.write(f"Level {diff.upper()}: {lev['level']} ({lev['detail']})\n")
        f.write(f"\nFiles:\n")
        for filename in extracted:
            f.write(f"  {filename}\n")

    return song_dir
