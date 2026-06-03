"""
Malody .mc 格式生成模块

将内部谱面数据结构转换为 Malody V 可导入的 .mc / .mcz 格式。
"""

import json
import zipfile
import subprocess
import shutil
from pathlib import Path
from fractions import Fraction
from typing import List, Optional, Tuple

from .eve_parser import EVEChart


def fraction_to_beat(frac: Fraction) -> List[int]:
    frac = frac.limit_denominator(10000)
    measure = int(frac // 4)
    remainder = frac - measure * 4
    if remainder == 0:
        return [measure, 0, 1]
    remainder = remainder.limit_denominator(10000)
    return [measure, remainder.numerator, remainder.denominator]


def generate_mc(chart: EVEChart, song_title: str, artist: str,
                difficulty: str, level: str, audio_file: str,
                offset_ms: int = 0) -> dict:
    meta = {
        "song": song_title, "artist": artist,
        "charter": f"Jubeat ({difficulty})",
        "bpm": chart.bpm_changes[0].bpm if chart.bpm_changes else 120.0,
        "mode": "key", "mode_ext": 16, "version": 2,
        "difficulty": {"BSC": 0, "ADV": 1, "EXT": 2}.get(difficulty, 0),
        "level": level, "audio": audio_file, "offset": offset_ms,
    }
    time_events = [{"beat": fraction_to_beat(bc.beat), "bpm": round(bc.bpm, 3)}
                   for bc in chart.bpm_changes]
    note_events = []
    for tap in chart.tap_notes:
        note_events.append({"beat": fraction_to_beat(tap.beat), "index": tap.position, "type": 0})
    for ln in chart.long_notes:
        note_events.append({"beat": fraction_to_beat(ln.beat), "index": ln.position,
                            "type": 1, "endbeat": fraction_to_beat(ln.end_beat),
                            "endindex": ln.end_position})
    note_events.sort(key=lambda n: n["beat"][0] * 4 + (n["beat"][1] / n["beat"][2] if n["beat"][2] else 0))
    return {"meta": meta, "time": time_events, "note": note_events}


def parse_song_info(info_path: Path) -> dict:
    info = {"music_id": "", "name": "", "bpm": 120.0, "levels": {}, "files": []}
    with open(info_path, 'r', encoding='utf-8') as f:
        section = None
        for line in f:
            line = line.strip()
            if line.startswith("Music ID:"):
                info["music_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("BPM:"):
                try: info["bpm"] = float(line.split(":", 1)[1].strip())
                except ValueError: pass
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
    try:
        r = subprocess.run(["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "libvorbis",
                            "-q:a", "4", str(ogg_path)], capture_output=True, timeout=60)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def convert_song(song_dir: Path, output_dir: Path, skip_existing: bool = False) -> Optional[Path]:
    from .eve_parser import parse_eve_file

    info_path = song_dir / "song_info.txt"
    if not info_path.exists():
        return None

    info = parse_song_info(info_path)
    song_name = info["name"] or info["music_id"] or song_dir.name
    safe_name = "".join(c if c.isalnum() or c in " _-()（）" else "_" for c in song_name) or song_dir.name

    song_output_dir = output_dir / safe_name
    bgm_wav = song_dir / "bgm.wav"
    bgm_ogg = song_dir / "bgm.ogg"
    audio_filename = "bgm.ogg"

    if not bgm_wav.exists() and not bgm_ogg.exists():
        return None

    diff_map = {"BSC": "bsc.eve", "ADV": "adv.eve", "EXT": "ext.eve"}
    mc_files = []

    for diff_name, eve_fn in diff_map.items():
        eve_path = song_dir / eve_fn
        if not eve_path.exists():
            continue
        level = info["levels"].get(diff_name, "?")
        try:
            chart = parse_eve_file(eve_path)
            mc_data = generate_mc(chart=chart, song_title=song_name, artist="Konami",
                                  difficulty=diff_name, level=level, audio_file=audio_filename)
            mc_filename = f"{safe_name}_{diff_name.lower()}.mc"
            mc_path = song_output_dir / mc_filename
            song_output_dir.mkdir(parents=True, exist_ok=True)
            with open(mc_path, 'w', encoding='utf-8') as f:
                json.dump(mc_data, f, ensure_ascii=False, indent=2)
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
                for mc_fn, mc_path in mc_files:
                    with open(mc_path, 'r', encoding='utf-8') as f:
                        d = json.load(f)
                    d["meta"]["audio"] = audio_filename
                    with open(mc_path, 'w', encoding='utf-8') as f:
                        json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 打包 .mcz
    mcz_path = output_dir / f"{safe_name}.mcz"
    try:
        with zipfile.ZipFile(mcz_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for mc_fn, mc_path in mc_files:
                zf.write(mc_path, mc_fn)
            audio_path = song_output_dir / audio_filename
            if audio_path.exists():
                zf.write(audio_path, audio_filename)
    except Exception:
        return None

    return mcz_path
