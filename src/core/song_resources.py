"""
解包后歌曲目录内的资源解析（EVE / 音频 / 封面）。

Beyond Ave 等版本经 ifstools rename_dupes 后常见 bsc_2.eve 命名，
jubeatools 仅识别 stem 为 bsc/adv/ext 的文件，此处统一解析。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

DIFFICULTIES = ("BSC", "ADV", "EXT")
_DIFF_PREFIX = {"BSC": "bsc", "ADV": "adv", "EXT": "ext"}


def resolve_eve_path(song_dir: Path, difficulty: str) -> Optional[Path]:
    """为指定难度选取最合适的 EVE 文件。"""
    prefix = _DIFF_PREFIX.get(difficulty.upper())
    if not prefix or not song_dir.is_dir():
        return None

    candidates: List[Tuple[int, int, Path]] = []
    for path in song_dir.glob("*.eve"):
        stem = path.stem.lower()
        if stem == prefix:
            score = 0
        elif stem.startswith(prefix + "_"):
            score = len(stem[len(prefix) + 1 :].split("_"))
        else:
            continue
        candidates.append((score, -path.stat().st_size, path))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def resolve_eve_map(song_dir: Path) -> Dict[str, Path]:
    """返回各难度对应的 EVE 路径（仅包含存在的难度）。"""
    return {
        diff: path
        for diff in DIFFICULTIES
        if (path := resolve_eve_path(song_dir, diff)) is not None
    }


def resolve_audio_path(song_dir: Path) -> Optional[Path]:
    """查找可播放的音频文件，优先已有解码结果。"""
    if not song_dir.is_dir():
        return None

    for name in ("bgm.wav", "bgm.ogg", "bgm.mp3"):
        path = song_dir / name
        if path.is_file():
            return path

    bgm_bins: List[Path] = []
    for path in song_dir.glob("bgm*.bin"):
        if path.is_file():
            bgm_bins.append(path)

    for preferred in ("bgm.bin", "bgm_1.bin"):
        candidate = song_dir / preferred
        if candidate in bgm_bins:
            return candidate

    if bgm_bins:
        bgm_bins.sort(key=lambda p: (len(p.name), -p.stat().st_size))
        return bgm_bins[0]
    return None


def ensure_playable_audio(song_dir: Path) -> Optional[Path]:
    """确保目录内有可播放音频；必要时将 bgm*.bin 转为 bgm.wav。"""
    existing = resolve_audio_path(song_dir)
    if existing is None:
        return None
    if existing.suffix.lower() != ".bin":
        return existing

    wav_path = song_dir / "bgm.wav"
    if wav_path.is_file():
        return wav_path

    from .unpacker import convert_bmp_to_wav

    if convert_bmp_to_wav(existing, wav_path):
        return wav_path
    return None


def resolve_jacket_path(song_dir: Path, info: Optional[dict] = None) -> Optional[Path]:
    """查找封面图路径。"""
    from .malody_writer import _find_image

    _, path = _find_image(song_dir, info)
    return path


def summarize_resources(song_dir: Path, info: Optional[dict] = None) -> dict:
    """汇总目录资源状态，供管理页表格使用。"""
    eve_map = resolve_eve_map(song_dir)
    audio = resolve_audio_path(song_dir)
    jacket = resolve_jacket_path(song_dir, info)

    return {
        "eve_map": eve_map,
        "eve_summary": "/".join(diff for diff in DIFFICULTIES if diff in eve_map) or "-",
        "has_audio": audio is not None,
        "audio_name": audio.name if audio else "",
        "has_wav": (song_dir / "bgm.wav").is_file(),
        "has_jacket": jacket is not None,
        "jacket_path": jacket,
    }


def build_beat_to_seconds(
    bpms: List[Tuple[float, float]], default_bpm: float = 120.0
) -> Callable[[float], float]:
    """将谱面 beat 时间转为秒（分段常数 BPM）。"""
    if not bpms:
        return lambda beat: beat * 60.0 / default_bpm

    segments = sorted(bpms, key=lambda item: item[0])
    if segments[0][0] > 0:
        segments = [(0.0, segments[0][1])] + segments

    def beat_to_seconds(target_beat: float) -> float:
        elapsed = 0.0
        current_beat = 0.0
        current_bpm = segments[0][1] or default_bpm

        for beat, bpm in segments[1:]:
            if beat >= target_beat:
                break
            bpm_val = bpm or current_bpm or default_bpm
            elapsed += (beat - current_beat) * 60.0 / bpm_val
            current_beat = beat
            current_bpm = bpm_val

        bpm_val = current_bpm or default_bpm
        elapsed += (target_beat - current_beat) * 60.0 / bpm_val
        return elapsed

    return beat_to_seconds
