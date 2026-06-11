"""WAV 响度归一化（解包 / 转 Malody 前使用）。

参考国服提取：`debug_out/cn_extract/10000036_bass 2 bass/bgm.ogg`
  RMS ≈ -14.6 dB
"""

from __future__ import annotations

import array
import math
import subprocess
import wave
from pathlib import Path
from typing import Optional, Tuple

# 国服参考曲 bgm.ogg 实测电平（`cn_extract/10000036_bass 2 bass/bgm.ogg`）
TARGET_EXPORT_RMS_DB = -14.61
# WAV→OGG (libvorbis) 后 RMS 约降低 0.45 dB，预先补偿
OGG_RMS_OFFSET_DB = 0.45
TARGET_WAV_RMS_DB = TARGET_EXPORT_RMS_DB + OGG_RMS_OFFSET_DB
NORMALIZE_MARKER_VERSION = "rms:-14.61+ogg"


def _gain_marker(wav_path: Path) -> Path:
    return wav_path.with_suffix(wav_path.suffix + ".gain")


def measure_pcm_levels(pcm: bytes) -> Tuple[float, float]:
    """返回 (rms_db, peak_db)，空数据为 (-inf, -inf)。"""
    if not pcm:
        return float("-inf"), float("-inf")
    n = len(pcm) // 2
    if n == 0:
        return float("-inf"), float("-inf")

    total = 0.0
    peak = 0
    for i in range(0, len(pcm), 2):
        sample = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        total += sample * sample
        if abs(sample) > peak:
            peak = abs(sample)

    rms = math.sqrt(total / n)
    if rms <= 0:
        rms_db = float("-inf")
    else:
        rms_db = 20.0 * math.log10(rms / 32768.0)

    if peak <= 0:
        peak_db = float("-inf")
    else:
        peak_db = 20.0 * math.log10(peak / 32768.0)

    return rms_db, peak_db


def read_normalize_marker(wav_path: Path) -> str:
    marker = _gain_marker(wav_path)
    if not marker.is_file():
        return ""
    return marker.read_text(encoding="ascii").strip()


def is_export_normalized(wav_path: Path) -> bool:
    return read_normalize_marker(wav_path) == NORMALIZE_MARKER_VERSION


def mark_export_normalized(wav_path: Path) -> None:
    _gain_marker(wav_path).write_text(NORMALIZE_MARKER_VERSION, encoding="ascii")


def amplify_pcm(pcm: bytes, gain: float) -> bytes:
    """对 16-bit PCM 样本应用增益并限幅。"""
    if gain == 1.0 or not pcm:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm)
    for i in range(len(samples)):
        value = int(samples[i] * gain)
        if value > 32767:
            value = 32767
        elif value < -32768:
            value = -32768
        samples[i] = value
    return samples.tobytes()


def normalize_pcm_for_export(pcm: bytes, target_rms_db: float = TARGET_WAV_RMS_DB) -> bytes:
    """将 PCM 归一化到目标平均电平（RMS）。"""
    rms_db, _ = measure_pcm_levels(pcm)
    if not math.isfinite(rms_db):
        return pcm
    gain = 10.0 ** ((target_rms_db - rms_db) / 20.0)
    if abs(gain - 1.0) < 1e-6:
        return pcm
    return amplify_pcm(pcm, gain)


def normalize_wav_file(
    wav_path: Path,
    target_rms_db: float = TARGET_WAV_RMS_DB,
) -> bool:
    """就地归一化 WAV 到目标 RMS。"""
    if not wav_path.is_file():
        return False
    try:
        with wave.open(str(wav_path), "rb") as src:
            params = src.getparams()
            pcm = src.readframes(params.nframes)
        normalized = normalize_pcm_for_export(pcm, target_rms_db)
        with wave.open(str(wav_path), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(normalized)
        mark_export_normalized(wav_path)
        return True
    except Exception:
        return False


def _find_bgm_bin(song_dir: Path) -> Optional[Path]:
    bins = [p for p in song_dir.glob("bgm*.bin") if p.is_file()]
    if not bins:
        return None
    for preferred in ("bgm.bin", "bgm_1.bin"):
        candidate = song_dir / preferred
        if candidate in bins:
            return candidate
    bins.sort(key=lambda p: (len(p.name), -p.stat().st_size))
    return bins[0]


def _decode_ogg_pcm(ogg_path: Path) -> bytes:
    r = subprocess.run(
        [
            "ffmpeg", "-i", str(ogg_path),
            "-f", "s16le", "-acodec", "pcm_s16le", "-",
        ],
        capture_output=True,
        timeout=120,
    )
    if r.returncode != 0:
        return b""
    return r.stdout


def _encode_wav_to_ogg(wav_path: Path, ogg_path: Path, gain_db: float) -> bool:
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_path),
        "-af", f"volume={gain_db:.2f}dB",
        "-c:a", "libvorbis", "-q:a", "4", str(ogg_path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return r.returncode == 0 and ogg_path.is_file()


def convert_wav_to_ogg_for_export(wav_path: Path, ogg_path: Path) -> bool:
    """WAV→OGG，并按国服参考 RMS 补偿编码衰减（必要时二次微调）。"""
    if not wav_path.is_file():
        return False
    try:
        with wave.open(str(wav_path), "rb") as src:
            pcm = src.readframes(src.getnframes())
        wav_rms, _ = measure_pcm_levels(pcm)
        if math.isfinite(wav_rms):
            gain_db = TARGET_EXPORT_RMS_DB - wav_rms + OGG_RMS_OFFSET_DB
        else:
            gain_db = 0.0

        if not _encode_wav_to_ogg(wav_path, ogg_path, gain_db):
            return False

        ogg_pcm = _decode_ogg_pcm(ogg_path)
        if not ogg_pcm:
            return True

        ogg_rms, _ = measure_pcm_levels(ogg_pcm)
        if not math.isfinite(ogg_rms):
            return True

        correction_db = TARGET_EXPORT_RMS_DB - ogg_rms
        if abs(correction_db) <= 0.12:
            return True

        return _encode_wav_to_ogg(wav_path, ogg_path, gain_db + correction_db)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def prepare_export_audio(song_dir: Path) -> Optional[Path]:
    """转 Malody 前准备 bgm.wav：优先从 bin 重解码并归一化。"""
    wav_path = song_dir / "bgm.wav"
    bgm_bin = _find_bgm_bin(song_dir)

    if bgm_bin is not None and not is_export_normalized(wav_path):
        from .konami_bmp import convert_bmp_file

        if convert_bmp_file(bgm_bin, wav_path):
            return wav_path

    if wav_path.is_file() and not is_export_normalized(wav_path):
        normalize_wav_file(wav_path)
        return wav_path

    return wav_path if wav_path.is_file() else None


# 兼容旧调用
def ensure_export_gain(wav_path: Path, target_gain: float = 1.0) -> bool:
    """转 Malody 前确保 WAV 已按参考 RMS 归一化。"""
    if not wav_path.is_file():
        return False
    if is_export_normalized(wav_path):
        return True
    return normalize_wav_file(wav_path)
