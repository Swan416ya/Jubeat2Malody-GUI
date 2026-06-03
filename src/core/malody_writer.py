"""
Malody .mc 格式生成模块 — 基于 jubeatools

核心转换逻辑复用 jubeatools:
- EVE→Song 加载: jubeatools.formats.konami.eve.load
- Song→Malody 导出: jubeatools.formats.malody.dump
- beat→fraction tuple 转换: jubeatools beats_to_fraction_tuple

本模块仅负责:
- music_info.xml / song_info.txt 元数据读取
- 音频格式转换 (WAV→OGG, BMP→WAV)
- .mcz 打包
"""

import json
import zipfile
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
from decimal import Decimal

from jubeatools import song
from jubeatools.formats.malody.dump import dump_malody_chart
from jubeatools.formats.malody import schema as malody
import simplejson

from .eve_parser import load_eve_chart, load_eve_song, FILENAME_TO_DIFFICULTY


def _generate_mc_bytes(
    metadata: song.Metadata,
    diff_name: str,
    chart: song.Chart,
) -> bytes:
    """使用 jubeatools 生成 .mc 文件内容 (bytes)"""
    # chart.timing 为 None 时使用空 timing
    timing = chart.timing or song.Timing(
        events=[song.BPMEvent(time=0, BPM=Decimal("120"))],
        beat_zero_offset=Decimal("0"),
    )

    malody_chart = dump_malody_chart(metadata, diff_name, chart, timing)
    json_chart = malody.CHART_SCHEMA.dump(malody_chart)
    return simplejson.dumps(json_chart, indent=4, use_decimal=True).encode("utf-8")


def parse_song_info(info_path: Path) -> dict:
    """解析 song_info.txt，返回歌曲元数据字典"""
    info = {
        "music_id": "", "name": "", "japanese_name": "", "ascii_name": "",
        "bpm_min": 120.0, "bpm_max": 120.0, "levels": {}, "files": [],
    }
    with open(info_path, "r", encoding="utf-8") as f:
        section = None
        for line in f:
            line = line.strip()
            if line.startswith("Music ID:"):
                info["music_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Japanese Name:"):
                info["japanese_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("ASCII Name:"):
                info["ascii_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("BPM (ref):") or line.startswith("BPM:"):
                bpm_str = line.split(":", 1)[1].strip()
                if "-" in bpm_str:
                    parts = bpm_str.split("-")
                    try:
                        info["bpm_min"] = float(parts[0].strip())
                        info["bpm_max"] = float(parts[1].strip())
                    except ValueError:
                        pass
                else:
                    try:
                        info["bpm_min"] = info["bpm_max"] = float(bpm_str)
                    except ValueError:
                        pass
            elif line.startswith("Level "):
                parts = line.split(":", 1)
                diff = parts[0].replace("Level", "").strip()
                info["levels"][diff] = parts[1].strip().split("(")[0].strip()
            elif line == "Files:":
                section = "files"
            elif section == "files" and line:
                info["files"].append(line)
    return info


def convert_wav_to_ogg(wav_path: Path, ogg_path: Path) -> bool:
    """使用 ffmpeg 将 WAV 转换为 OGG Vorbis"""
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "libvorbis",
             "-q:a", "4", str(ogg_path)],
            capture_output=True, timeout=60,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _find_image(song_dir: Path) -> Tuple[str, Optional[Path]]:
    """在歌曲目录中查找封面/背景图片"""
    for pattern in ["jkt*", "jacket*", "cover*", "art*"]:
        for f in song_dir.iterdir():
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                import fnmatch
                if fnmatch.fnmatch(f.name.lower(), pattern.lower()):
                    return f.name, f
    for f in song_dir.iterdir():
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
            return f.name, f
    return "", None


def _build_metadata(
    song_name: str,
    artist: str = "Konami",
    audio_path: Optional[Path] = None,
    cover_path: Optional[Path] = None,
) -> song.Metadata:
    """构建 jubeatools Metadata 对象"""
    return song.Metadata(
        title=song_name,
        artist=artist,
        audio=audio_path,
        cover=cover_path,
    )


def convert_song(song_dir: Path, output_dir: Path, skip_existing: bool = False) -> Optional[Path]:
    """从解包后的歌曲目录转换为 Malody .mcz

    Args:
        song_dir: 包含 song_info.txt + .eve + 音频的目录
        output_dir: .mcz 输出目录
        skip_existing: 是否跳过已存在的文件
    """
    info_path = song_dir / "song_info.txt"
    if not info_path.exists():
        return None

    info = parse_song_info(info_path)
    song_name = info["name"] or info["music_id"] or song_dir.name
    safe_name = "".join(
        c if c.isalnum() or c in " _-()（）" else "_" for c in song_name
    ) or song_dir.name

    song_output_dir = output_dir / safe_name
    bgm_wav = song_dir / "bgm.wav"
    bgm_ogg = song_dir / "bgm.ogg"
    audio_filename = "bgm.ogg"

    if not bgm_wav.exists() and not bgm_ogg.exists():
        return None

    # 查找封面图
    img_filename, img_path = _find_image(song_dir)

    # 使用 jubeatools 加载所有 EVE 文件
    try:
        jt_song = load_eve_song(song_dir)
    except Exception:
        return None

    if not jt_song.charts:
        return None

    # 设置元数据
    audio_for_metadata = Path(audio_filename) if audio_filename else None
    cover_for_metadata = Path(img_filename) if img_filename else None
    jt_song.metadata = _build_metadata(
        song_name, "Konami", audio_for_metadata, cover_for_metadata
    )

    # 生成各难度的 .mc 文件
    mc_files = []
    for diff_name, chart in jt_song.charts.items():
        try:
            mc_bytes = _generate_mc_bytes(jt_song.metadata, diff_name, chart)
            mc_filename = f"{safe_name}_{diff_name.lower()}.mc"
            mc_path = song_output_dir / mc_filename
            song_output_dir.mkdir(parents=True, exist_ok=True)
            mc_path.write_bytes(mc_bytes)
            mc_files.append((mc_filename, mc_path))
        except Exception:
            continue

    if not mc_files:
        return None

    # 音频处理
    try:
        dest_audio = song_output_dir / audio_filename
        if bgm_ogg.exists():
            shutil.copy2(bgm_ogg, dest_audio)
        elif bgm_wav.exists():
            if not convert_wav_to_ogg(bgm_wav, dest_audio):
                shutil.copy2(bgm_wav, song_output_dir / "bgm.wav")
                audio_filename = "bgm.wav"
    except Exception:
        pass

    # 打包 .mcz (文件放在 0/ 目录下，Malody 导入要求此结构)
    mcz_path = output_dir / f"{safe_name}.mcz"
    try:
        with zipfile.ZipFile(mcz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for mc_fn, mc_path in mc_files:
                zf.write(mc_path, f"0/{mc_fn}")
            audio_path = song_output_dir / audio_filename
            if audio_path.exists():
                zf.write(audio_path, f"0/{audio_filename}")
            if img_path and img_path.exists():
                zf.write(img_path, f"0/{img_filename}")
    except Exception:
        return None

    return mcz_path


def convert_single_song(
    song_dir: Path, output_dir: Path, skip_existing: bool = False
) -> Optional[Path]:
    """从包含音频+谱面的单歌文件夹直接转换为 Malody .mcz

    文件夹结构:
        song_dir/
          ├── bgm.wav (或 bgm.ogg)
          ├── bsc.eve
          ├── adv.eve
          ├── ext.eve
          ├── jkt_*.png (可选，封面图)
          └── song_info.txt (可选，有则读取元数据)
    """
    if not song_dir.is_dir():
        return None

    safe_name = song_dir.name
    mcz_path = output_dir / f"{safe_name}.mcz"
    if skip_existing and mcz_path.exists():
        return mcz_path

    # 读取元数据 (可选)
    info_path = song_dir / "song_info.txt"
    info = {}
    if info_path.exists():
        info = parse_song_info(info_path)

    song_name = info.get("name", "") or song_dir.name

    # 查找封面图
    img_filename, img_path = _find_image(song_dir)

    # 查找音频文件
    audio_src = None
    audio_filename = "bgm.ogg"
    for candidate in ["bgm.ogg", "bgm.wav", "bgm.bin"]:
        p = song_dir / candidate
        if p.exists():
            audio_src = p
            if candidate == "bgm.wav":
                audio_filename = "bgm.ogg"
            elif candidate == "bgm.bin":
                audio_filename = "bgm.ogg"
            else:
                audio_filename = candidate
            break

    if audio_src is None:
        for ext in [".ogg", ".wav", ".mp3"]:
            for f in song_dir.iterdir():
                if f.suffix.lower() == ext:
                    audio_src = f
                    audio_filename = f.name
                    break
            if audio_src:
                break

    if audio_src is None:
        return None

    # 使用 jubeatools 加载所有 EVE 文件
    try:
        jt_song = load_eve_song(song_dir)
    except Exception:
        return None

    if not jt_song.charts:
        return None

    # 设置元数据
    audio_for_metadata = Path(audio_filename) if audio_filename else None
    cover_for_metadata = Path(img_filename) if img_filename else None
    jt_song.metadata = _build_metadata(
        song_name, "Konami", audio_for_metadata, cover_for_metadata
    )

    # 生成各难度的 .mc 文件
    mc_files = []
    for diff_name, chart in jt_song.charts.items():
        try:
            mc_bytes = _generate_mc_bytes(jt_song.metadata, diff_name, chart)
            mc_filename = f"{safe_name}_{diff_name.lower()}.mc"
            mc_path = song_dir / mc_filename  # 临时写到源目录
            mc_path.write_bytes(mc_bytes)
            mc_files.append((mc_filename, mc_path))
        except Exception:
            continue

    if not mc_files:
        return None

    # 音频处理
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / safe_name
    temp_dir.mkdir(parents=True, exist_ok=True)

    dest_audio = temp_dir / audio_filename
    final_audio_filename = audio_filename

    try:
        if audio_src.suffix.lower() == ".ogg":
            shutil.copy2(audio_src, dest_audio)
        elif audio_src.suffix.lower() == ".wav":
            if not convert_wav_to_ogg(audio_src, dest_audio):
                final_audio_filename = audio_src.name
                shutil.copy2(audio_src, temp_dir / audio_src.name)
        elif audio_src.suffix.lower() == ".bin":
            from .unpacker import convert_bmp_to_wav
            wav_path = temp_dir / "bgm.wav"
            if convert_bmp_to_wav(audio_src, wav_path):
                if not convert_wav_to_ogg(wav_path, dest_audio):
                    final_audio_filename = "bgm.wav"
            else:
                return None
        else:
            shutil.copy2(audio_src, dest_audio)
    except Exception:
        return None

    # 打包 .mcz
    try:
        with zipfile.ZipFile(mcz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for mc_fn, mc_path in mc_files:
                zf.write(mc_path, f"0/{mc_fn}")
            audio_path = temp_dir / final_audio_filename
            if audio_path.exists():
                zf.write(audio_path, f"0/{final_audio_filename}")
            if img_path and img_path.exists():
                zf.write(img_path, f"0/{img_filename}")
    except Exception:
        return None
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            for mc_fn, mc_path in mc_files:
                mc_path.unlink(missing_ok=True)
        except Exception:
            pass

    return mcz_path
