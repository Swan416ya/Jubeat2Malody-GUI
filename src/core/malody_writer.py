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
import re
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

from .eve_parser import load_eve_song
from .unpacker import _finalize_song_info, resolve_display_title, resolve_artist

# Malody Jubeat 谱面使用 1/4 拍精度 (与 extra.divide=4 一致)
MALODY_BEAT_DIVIDE = 4
MALODY_BEAT_SNAP = 4


def _beat_to_float(beat) -> float:
    return beat[0] + beat[1] / beat[2]


def _float_to_beat(value: float, divide: int = MALODY_BEAT_DIVIDE) -> List[int]:
    """将拍数转换为 Malody 分数拍格式 [小节, 分子, 分母]"""
    if value < 0:
        value = 0.0
    measure = int(value)
    frac = value - measure
    num = round(frac * divide)
    if num >= divide:
        measure += 1
        num = 0
    return [measure, num, divide]


def _normalize_malody_chart(json_chart: dict) -> None:
    """将 beat 统一量化到 1/4 拍，并精简 BPM 段（Malody 无法处理 1/240 精度）"""
    divide = MALODY_BEAT_DIVIDE

    normalized_time: List[dict] = []
    last_bpm = None
    for entry in sorted(json_chart.get("time", []), key=lambda e: _beat_to_float(e["beat"])):
        beat = _float_to_beat(_beat_to_float(entry["beat"]), divide)
        bpm = float(entry["bpm"])
        if last_bpm is not None and abs(bpm - last_bpm) < 1.0:
            continue
        if normalized_time and beat == normalized_time[-1]["beat"]:
            normalized_time[-1]["bpm"] = bpm
        else:
            normalized_time.append({"beat": beat, "bpm": bpm})
        last_bpm = bpm

    if not normalized_time:
        normalized_time = [{"beat": [0, 0, divide], "bpm": 120.0}]
    json_chart["time"] = normalized_time[:16]

    normalized_notes: List[dict] = []
    for note in json_chart.get("note", []):
        n = dict(note)
        if "beat" in n:
            n["beat"] = _float_to_beat(_beat_to_float(n["beat"]), divide)
        if "endbeat" in n:
            n["endbeat"] = _float_to_beat(_beat_to_float(n["endbeat"]), divide)
            if _beat_to_float(n["endbeat"]) <= _beat_to_float(n["beat"]):
                continue
        normalized_notes.append(n)

    normalized_notes.sort(
        key=lambda n: (
            _beat_to_float(n.get("beat", [0, 0, 1])),
            0 if "sound" in n else 1,
            n.get("index", -1),
        )
    )
    json_chart["note"] = normalized_notes


def _simplify_timing_for_malody(
    timing: song.Timing, threshold: float = 1.0, max_events: int = 16
) -> song.Timing:
    """精简 BPM 变化列表，避免 Malody 因过多变速段卡死

    Jubeat 谱面常有数百个渐变 TEMPO 事件，Malody 只需关键 BPM 节点。
    """
    if not timing.events:
        return timing

    events = sorted(timing.events, key=lambda e: e.time)
    if len(events) <= max_events:
        return timing

    simplified: List[song.BPMEvent] = [events[0]]
    for ev in events[1:]:
        prev = simplified[-1]
        if ev.time == prev.time:
            simplified[-1] = ev
            continue
        if abs(float(ev.BPM) - float(prev.BPM)) < threshold:
            continue
        simplified.append(ev)

    if len(simplified) > max_events and threshold < 8:
        return _simplify_timing_for_malody(
            timing, threshold=threshold * 2, max_events=max_events
        )

    return song.Timing(
        events=simplified,
        beat_zero_offset=timing.beat_zero_offset,
    )


def _resolve_timing(
    timing: Optional[song.Timing], info: Optional[dict] = None
) -> song.Timing:
    """解析/补全 timing，确保 beat 0 有 BPM 事件

    优先使用 EVE 解析结果；无 TEMPO 时回退到 song_info 参考 BPM。
    """
    ref_bpm = Decimal(str(
        (info or {}).get("bpm_max")
        or (info or {}).get("bpm_min")
        or 120
    ))

    if timing is None or not timing.events:
        return song.Timing(
            events=[song.BPMEvent(time=0, BPM=ref_bpm)],
            beat_zero_offset=Decimal("0"),
        )

    events = sorted(timing.events, key=lambda e: e.time)
    if events[0].time != 0:
        events = [song.BPMEvent(time=0, BPM=events[0].BPM), *events]

    resolved = song.Timing(
        events=events,
        beat_zero_offset=timing.beat_zero_offset,
    )
    return _simplify_timing_for_malody(resolved)


def _generate_mc_bytes(
    metadata: song.Metadata,
    diff_name: str,
    chart: song.Chart,
    timing: song.Timing,
    audio_filename: Optional[str] = None,
    level: Optional[str] = None,
    cover_filename: Optional[str] = None,
) -> bytes:
    """使用 jubeatools 生成 .mc 文件内容 (bytes)

    在 jubeatools 输出基础上补全 Malody 必需字段:
    - meta.mode_ext: 模式扩展参数 (Malody V 要求)
    - extra: 编辑器附加信息 (Malody V 要求)

    Args:
        timing: 由 iter_charts_with_applicable_timing 或 _resolve_timing 提供
        audio_filename: 实际音频文件名，用于修正 Sound 事件中的路径
        level: 难度等级 (来自 music_info.xml)
        cover_filename: 曲绘文件名，写入 meta.background
    """
    malody_chart = dump_malody_chart(metadata, diff_name, chart, timing)
    json_chart = malody.CHART_SCHEMA.dump(malody_chart)

    meta = json_chart.setdefault("meta", {})

    # 1. meta.mode_ext — 真实 PAD 谱面测试数据中包含此字段
    if "mode_ext" not in meta:
        meta["mode_ext"] = {}

    # 2. 封面 — Malody 通过 meta.background 关联曲绘文件
    if cover_filename:
        meta["background"] = cover_filename

    # 3. 难度等级
    if level:
        meta["level"] = level

    # 4. extra — Malody 编辑器附加信息，真实谱面均包含此字段
    if "extra" not in json_chart:
        json_chart["extra"] = {
            diff_name: {
                "divide": 4,
                "speed": 100,
                "save": 0,
                "lock": 0,
                "edit_mode": 0,
            }
        }

    # 5. 将节拍统一量化到 1/4 拍，避免 Malody 解析 1/240 精度时卡死
    _normalize_malody_chart(json_chart)

    # 6. 修正 Sound 事件中的音频文件名
    if audio_filename:
        for note in json_chart.get("note", []):
            if "sound" in note:
                note["sound"] = audio_filename

    return simplejson.dumps(json_chart, indent=4, use_decimal=True).encode("utf-8")


def enrich_song_info(info: dict) -> dict:
    """合并参考库 / atwiki / 用户表，补全曲名与曲师。"""
    try:
        music_id = int(info.get("music_id") or 0)
    except (TypeError, ValueError):
        music_id = 0
    if music_id <= 0:
        return info
    return _finalize_song_info(info, music_id, None)


def _metadata_from_info(
    info: dict,
    audio_path: Optional[Path] = None,
    cover_path: Optional[Path] = None,
) -> song.Metadata:
    """从 song_info 构建 jubeatools Metadata"""
    info = enrich_song_info(info)
    song_name = resolve_display_title(info) or info.get("name", "")
    artist = resolve_artist(info)
    return _build_metadata(song_name, artist or "Unknown Artist", audio_path, cover_path)


def _level_for_diff(info: dict, diff_name: str) -> Optional[str]:
    """从 song_info 获取对应难度的等级"""
    levels = info.get("levels", {})
    diff_key = diff_name.lower()
    if diff_key in levels:
        lev = levels[diff_key]
        if isinstance(lev, dict):
            detail = lev.get("detail")
            return str(detail) if detail is not None else str(lev.get("level", ""))
        return str(lev)
    return None


def parse_song_info(info_path: Path) -> dict:
    """解析 song_info.txt，返回歌曲元数据字典"""
    info = {
        "music_id": "", "name": "", "title_name": "", "japanese_name": "",
        "ascii_name": "", "artist": "", "artist_name": "", "copyright_name": "",
        "bpm_min": 120.0, "bpm_max": 120.0,
        "levels": {}, "files": [], "jacket": "",
    }
    with open(info_path, "r", encoding="utf-8") as f:
        section = None
        for line in f:
            line = line.strip()
            if line.startswith("Music ID:"):
                info["music_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Title Name:"):
                info["title_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Japanese Name:"):
                info["japanese_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("ASCII Name:"):
                info["ascii_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Artist:"):
                info["artist"] = line.split(":", 1)[1].strip()
                info["artist_name"] = info["artist"]
            elif line.startswith("Jacket:"):
                info["jacket"] = line.split(":", 1)[1].strip()
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
                diff = parts[0].replace("Level", "").strip().upper()
                level_text = parts[1].strip()
                level_val = level_text.split("(")[0].strip()
                detail_match = re.search(r"\(([\d.]+)\)", level_text)
                try:
                    detail = float(detail_match.group(1)) if detail_match else float(level_val)
                    level_num = int(float(level_val))
                except ValueError:
                    continue
                info["levels"][diff] = {"level": level_num, "detail": detail}
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


def _find_image(song_dir: Path, info: dict = None) -> Tuple[str, Optional[Path]]:
    """在歌曲目录中查找封面/背景图片"""
    import fnmatch

    # 如果 song_info.txt 中指定了 Jacket 文件名，优先使用
    if info and info.get("jacket"):
        jkt_name = info["jacket"]
        jkt_path = song_dir / jkt_name
        if jkt_path.exists():
            return jkt_name, jkt_path

    # 按优先级搜索图片（含子目录）
    for pattern in ["jkt*", "jacket*", "cover*", "art*"]:
        for f in song_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                if fnmatch.fnmatch(f.name.lower(), pattern.lower()):
                    return f.name, f
    for f in song_dir.rglob("*"):
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

    info = enrich_song_info(parse_song_info(info_path))
    song_name = resolve_display_title(info) or info.get("name") or info.get("music_id") or song_dir.name
    safe_name = "".join(
        c if c.isalnum() or c in " _-()（）" else "_" for c in song_name
    ) or song_dir.name

    song_output_dir = output_dir / safe_name
    bgm_wav = song_dir / "bgm.wav"
    bgm_ogg = song_dir / "bgm.ogg"
    audio_filename = "bgm.ogg"

    if not bgm_wav.exists() and not bgm_ogg.exists():
        from .unpacker import convert_bmp_to_wav

        for candidate in sorted(song_dir.glob("bgm*.bin")):
            if convert_bmp_to_wav(candidate, bgm_wav):
                break

    if not bgm_wav.exists() and not bgm_ogg.exists():
        return None

    # 查找封面图（仅当文件真实存在时才打包）
    img_filename, img_path = _find_image(song_dir, info)
    if not img_path or not img_path.exists():
        img_filename, img_path = "", None

    # 使用 jubeatools 加载所有 EVE 文件
    try:
        jt_song = load_eve_song(song_dir, beat_snap=MALODY_BEAT_SNAP)
    except Exception:
        return None

    if not jt_song.charts:
        return None

    # 音频处理（先生成音频，再生成 .mc，确保文件名一致）
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

    # 设置元数据
    audio_for_metadata = Path(audio_filename) if audio_filename else None
    cover_for_metadata = Path(img_filename) if img_filename else None
    jt_song.metadata = _metadata_from_info(
        info, audio_for_metadata, cover_for_metadata
    )

    # 生成各难度的 .mc 文件（传入实际音频文件名）
    mc_files = []
    for diff_name, chart, timing in jt_song.iter_charts_with_applicable_timing():
        try:
            resolved_timing = _resolve_timing(timing, info)
            level = _level_for_diff(info, diff_name)
            mc_bytes = _generate_mc_bytes(
                jt_song.metadata, diff_name, chart, resolved_timing,
                audio_filename=audio_filename, level=level,
                cover_filename=img_filename or None,
            )
            mc_filename = f"{safe_name}_{diff_name.lower()}.mc"
            mc_path = song_output_dir / mc_filename
            song_output_dir.mkdir(parents=True, exist_ok=True)
            mc_path.write_bytes(mc_bytes)
            mc_files.append((mc_filename, mc_path))
        except Exception:
            continue

    if not mc_files:
        return None

    # 打包 .mcz (文件放在 0/ 目录下，Malody 导入要求此结构)
    mcz_path = output_dir / f"{safe_name}.mcz"
    try:
        with zipfile.ZipFile(mcz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for mc_fn, mc_path in mc_files:
                zf.write(mc_path, f"0/{mc_fn}")
            audio_path = song_output_dir / audio_filename
            if audio_path.exists():
                zf.write(audio_path, f"0/{audio_filename}")
            if img_filename and img_path and img_path.exists():
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

    song_name = resolve_display_title(info) or info.get("name", "") or song_dir.name

    # 查找封面图（仅当文件真实存在时才打包）
    img_filename, img_path = _find_image(song_dir, info)
    if not img_path or not img_path.exists():
        img_filename, img_path = "", None

    # 查找音频文件
    audio_src = None
    audio_filename = "bgm.ogg"
    for candidate in ["bgm.ogg", "bgm.wav", "bgm.bin", "bgm_1.bin"]:
        p = song_dir / candidate
        if p.exists():
            audio_src = p
            if candidate in ("bgm.wav", "bgm.bin", "bgm_1.bin"):
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

    # 音频处理（先生成音频，再生成 .mc，确保文件名一致）
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

    # 使用 jubeatools 加载所有 EVE 文件
    try:
        jt_song = load_eve_song(song_dir, beat_snap=MALODY_BEAT_SNAP)
    except Exception:
        return None

    if not jt_song.charts:
        return None

    # 设置元数据
    audio_for_metadata = Path(final_audio_filename) if final_audio_filename else None
    cover_for_metadata = Path(img_filename) if img_filename else None
    jt_song.metadata = _metadata_from_info(
        info, audio_for_metadata, cover_for_metadata
    )

    # 生成各难度的 .mc 文件（传入实际音频文件名）
    mc_files = []
    for diff_name, chart, timing in jt_song.iter_charts_with_applicable_timing():
        try:
            resolved_timing = _resolve_timing(timing, info)
            level = _level_for_diff(info, diff_name)
            mc_bytes = _generate_mc_bytes(
                jt_song.metadata, diff_name, chart, resolved_timing,
                audio_filename=final_audio_filename, level=level,
                cover_filename=img_filename or None,
            )
            mc_filename = f"{safe_name}_{diff_name.lower()}.mc"
            mc_path = song_dir / mc_filename  # 临时写到源目录
            mc_path.write_bytes(mc_bytes)
            mc_files.append((mc_filename, mc_path))
        except Exception:
            continue

    if not mc_files:
        return None

    # 打包 .mcz
    try:
        with zipfile.ZipFile(mcz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for mc_fn, mc_path in mc_files:
                zf.write(mc_path, f"0/{mc_fn}")
            audio_path = temp_dir / final_audio_filename
            if audio_path.exists():
                zf.write(audio_path, f"0/{final_audio_filename}")
            if img_filename and img_path and img_path.exists():
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
