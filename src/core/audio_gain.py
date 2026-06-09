"""WAV 音量增益（解包 / 转 Malody 前使用）。"""

from __future__ import annotations

import array
import wave
from pathlib import Path

DEFAULT_EXPORT_GAIN = 4.0


def _gain_marker(wav_path: Path) -> Path:
    return wav_path.with_suffix(wav_path.suffix + ".gain")


def read_applied_gain(wav_path: Path) -> float:
    marker = _gain_marker(wav_path)
    if not marker.is_file():
        return 1.0
    try:
        return float(marker.read_text(encoding="ascii").strip())
    except ValueError:
        return 1.0


def is_gain_applied(wav_path: Path, target: float = DEFAULT_EXPORT_GAIN) -> bool:
    return read_applied_gain(wav_path) >= target - 1e-6


def mark_gain_applied(wav_path: Path, gain: float = DEFAULT_EXPORT_GAIN) -> None:
    _gain_marker(wav_path).write_text(str(gain), encoding="ascii")


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


def amplify_wav_file(wav_path: Path, gain: float) -> bool:
    """就地放大 WAV 文件音量。"""
    if gain == 1.0 or not wav_path.is_file():
        return wav_path.is_file()
    try:
        with wave.open(str(wav_path), "rb") as src:
            params = src.getparams()
            pcm = src.readframes(params.nframes)
        boosted = amplify_pcm(pcm, gain)
        with wave.open(str(wav_path), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(boosted)
        return True
    except Exception:
        return False


def ensure_export_gain(
    wav_path: Path,
    target_gain: float = DEFAULT_EXPORT_GAIN,
) -> bool:
    """转 Malody 前确保 WAV 达到目标增益（支持从旧版 2x 补到 4x）。"""
    if not wav_path.is_file():
        return False
    applied = read_applied_gain(wav_path)
    if applied >= target_gain - 1e-6:
        return True
    ratio = target_gain / applied
    if not amplify_wav_file(wav_path, ratio):
        return False
    mark_gain_applied(wav_path, target_gain)
    return True
