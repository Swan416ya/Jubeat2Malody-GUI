"""
Konami BMP audio (Jubeat / GITADORA / drummania).

BMP is OKI4S ADPCM (vgmstream coding_OKI4S, libbmsd-engine "adpcm"), not raw PCM.
Reference: vgmstream src/meta/bmp_konami.c, src/coding/oki_decoder.c
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Optional, Tuple

STEP_SIZES = (
    16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66,
    73, 80, 88, 97, 107, 118, 130, 143,
    157, 173, 190, 209, 230, 253, 279, 307,
    337, 371, 408, 449, 494, 544, 598, 658,
    724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552,
)

STEX_INDEXES = (
    -1, -1, -1, -1, 2, 4, 6, 8,
    -1, -1, -1, -1, 2, 4, 6, 8,
)


def _expand_nibble(byte_val: int, nibble_shift: int, hist1: int, step_index: int) -> Tuple[int, int]:
    code = (byte_val >> nibble_shift) & 0xF
    step = STEP_SIZES[step_index] << 4

    delta = step >> 3
    if code & 1:
        delta += step >> 2
    if code & 2:
        delta += step >> 1
    if code & 4:
        delta += step
    if code & 8:
        delta = -delta

    hist1 += delta
    if hist1 > 32767:
        hist1 = 32767
    elif hist1 < -32768:
        hist1 = -32768

    step_index += STEX_INDEXES[code]
    if step_index < 0:
        step_index = 0
    elif step_index > 48:
        step_index = 48

    return hist1, step_index


def decode_oki4s(adpcm: bytes, channels: int, num_samples: int) -> bytes:
    """Decode OKI4S ADPCM to interleaved int16 PCM."""
    if channels not in (1, 2):
        raise ValueError(f"unsupported channel count: {channels}")

    num_samples = min(num_samples, len(adpcm) if channels == 2 else len(adpcm) * 2)
    out = bytearray(num_samples * channels * 2)
    hists = [0, 0]
    steps = [0, 0]

    for i in range(num_samples):
        if channels == 2:
            byte_val = adpcm[i] if i < len(adpcm) else 0
            for ch in range(2):
                shift = 4 if ch == 0 else 0
                sample, steps[ch] = _expand_nibble(byte_val, shift, hists[ch], steps[ch])
                struct.pack_into("<h", out, (i * channels + ch) * 2, sample)
        else:
            byte_val = adpcm[i // 2] if (i // 2) < len(adpcm) else 0
            shift = 0 if (i & 1) else 4
            sample, steps[0] = _expand_nibble(byte_val, shift, hists[0], steps[0])
            struct.pack_into("<h", out, i * 2, sample)

    return bytes(out)


def parse_bmp_header(data: bytes) -> Optional[dict]:
    """Parse Konami BMP header. Returns None if not a valid BMP."""
    if len(data) < 0x20 or data[:4] != b"BMP\x00":
        return None

    num_samples, loop_start, loop_end = struct.unpack(">III", data[4:16])
    channels = data[0x10]
    if channels not in (1, 2):
        channels = struct.unpack("<H", data[16:18])[0]
    sample_rate = struct.unpack(">I", data[0x14:0x18])[0]

    if channels not in (1, 2) or sample_rate == 0:
        return None

    adpcm = data[0x20:]
    if num_samples == 0 or num_samples > len(adpcm) * (2 if channels == 1 else 1):
        num_samples = len(adpcm) if channels == 2 else len(adpcm) * 2

    return {
        "num_samples": num_samples,
        "loop_start": loop_start,
        "loop_end": loop_end,
        "channels": channels,
        "sample_rate": sample_rate,
        "adpcm": adpcm,
    }


def bmp_to_wav_bytes(data: bytes) -> Optional[Tuple[bytes, int, int]]:
    """Decode BMP file bytes to WAV file bytes. Returns (wav_bytes, rate, channels)."""
    header = parse_bmp_header(data)
    if not header:
        return None

    pcm = decode_oki4s(header["adpcm"], header["channels"], header["num_samples"])
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(header["channels"])
        wav.setsampwidth(2)
        wav.setframerate(header["sample_rate"])
        wav.writeframes(pcm)
    return buf.getvalue(), header["sample_rate"], header["channels"]


def convert_bmp_file(bmp_path: Path, wav_path: Path) -> bool:
    """Convert a Konami BMP .bin file to standard WAV."""
    try:
        data = bmp_path.read_bytes()
        result = bmp_to_wav_bytes(data)
        if not result:
            return False
        wav_bytes, _, _ = result
        wav_path.write_bytes(wav_bytes)
        return True
    except Exception:
        return False
