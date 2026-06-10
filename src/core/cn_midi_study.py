"""
国服 MIDI 与街机 EVE 对照研究工具。

已验证规律（见 compare_song 输出）：
- ticks_per_beat = 480
- 面板键位 = MIDI note - 36（36–51 → 16 键）
- 经典曲：note_on+note_off，单击 velocity=127，长按 tail=velocity-1
- 独占/新曲：仅 note_on，单击 velocity=100
- 同拍和弦：顺序可能不同，按拍聚合后 multiset 与 EVE 一致
"""

from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import mido
from jubeatools import song
from jubeatools.formats.konami.eve.load import load_file, iter_events
from jubeatools.formats.konami.load_tools import make_chart_from_events

from .cn_bundles import CnBundleIndex, _extract_text_asset, _read_varint, parse_jbt_song_list, _find_largest_song_list_blob
_DIFF_PREFIX = {"BSC": "bsc", "ADV": "adv", "EXT": "ext"}

_PANEL_BASE = 36
_TAP_VELOCITIES = frozenset({127, 100})
_DEFAULT_TPB = 480

# 国服日服都较常见、适合对照的曲目（music_id）
REFERENCE_SONG_IDS = (
    10000036,  # bass 2 bass — 纯 tap
    10000038,  # GIGA BREAK
    10000039,  # Icicles
    10000040,  # Jumping Boogie
    10000045,  # Chance and Dice
    11000009,  # Time Lapse — 含 long
    20000038,  # 隅田川夏恋歌
    50000109,  # ヒーロー
    70000007,  # Hunny Bunny — 含 long
    90000136,  # Winter Gift — 含 long
)


@dataclass
class DiffCompareResult:
    difficulty: str
    cn_taps: int
    eve_taps: int
    cn_longs: int
    eve_longs: int
    tap_multiset_match: bool
    long_match: int
    long_total: int


@dataclass
class SongCompareResult:
    music_id: int
    title: str
    cn_available: bool
    arcade_dir: Optional[Path]
    difficulties: List[DiffCompareResult]


def _ticks_to_beat(ticks: int, tpb: int = _DEFAULT_TPB) -> float:
    return ticks / tpb


def parse_cn_track_events(track, tpb: int = _DEFAULT_TPB) -> Tuple[List[Tuple[float, int]], List[Tuple[float, float, int, int]]]:
    """解析单轨 → (taps, longs)；longs = (beat, duration, pos, tail)。"""
    abs_tick = 0
    active: Dict[int, Tuple[int, int]] = {}
    taps: List[Tuple[float, int]] = []
    longs: List[Tuple[float, float, int, int]] = []

    for msg in track:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = (abs_tick, msg.velocity)
        elif msg.type in ("note_off",) or (msg.type == "note_on" and msg.velocity == 0):
            start = active.pop(msg.note, None)
            if start is None:
                continue
            start_tick, velocity = start
            duration = abs_tick - start_tick
            pos = msg.note - _PANEL_BASE
            if not (0 <= pos < 16):
                continue
            beat = _ticks_to_beat(start_tick, tpb)
            if velocity in _TAP_VELOCITIES:
                taps.append((round(beat, 4), pos))
            else:
                tail = velocity - 1
                if 0 <= tail < 16:
                    longs.append(
                        (
                            round(beat, 4),
                            round(_ticks_to_beat(duration, tpb), 4),
                            pos,
                            tail,
                        )
                    )

    return taps, longs


def parse_cn_midi_bytes(data: bytes, difficulty: str) -> Tuple[List, List]:
    midi = mido.MidiFile(file=io.BytesIO(data))
    diff_key = difficulty.lower()
    for track in midi.tracks:
        name = ""
        for msg in track:
            if msg.type == "track_name":
                name = msg.name.strip("\x00").lower()
                break
        if name == diff_key:
            return parse_cn_track_events(track, midi.ticks_per_beat)
    return [], []


def parse_eve_chart(eve_path: Path, beat_snap: int = 4) -> Tuple[List, List]:
    chart = make_chart_from_events(list(iter_events(load_file(eve_path))), beat_snap=beat_snap)
    taps = [(round(float(n.time), 4), n.position.index) for n in chart.notes if isinstance(n, song.TapNote)]
    longs = [
        (
            round(float(n.time), 4),
            round(float(n.duration), 4),
            n.position.index,
            n.tail_tip.index,
        )
        for n in chart.notes
        if isinstance(n, song.LongNote)
    ]
    return taps, longs


def _round_beat(beat: float, divide: int = 4) -> float:
    return round(beat * divide) / divide


def _multiset_by_beat(
    events: List[Tuple[float, int]],
    *,
    beat_divide: int = 4,
) -> Dict[float, Tuple[int, ...]]:
    """按拍聚合键位；默认量化到 1/4 拍，与 Malody 导出精度一致。"""
    grouped: Dict[float, List[int]] = defaultdict(list)
    for beat, pos in events:
        grouped[_round_beat(beat, beat_divide)].append(pos)
    return {beat: tuple(sorted(positions)) for beat, positions in grouped.items()}


def compare_difficulty(
    cn_taps: List,
    cn_longs: List,
    eve_taps: List,
    eve_longs: List,
    difficulty: str,
) -> DiffCompareResult:
    cn_by_beat = _multiset_by_beat(cn_taps)
    eve_by_beat = _multiset_by_beat(eve_taps)
    multiset_ok = cn_by_beat == eve_by_beat

    long_match = 0
    for item in cn_longs:
        for ev in eve_longs:
            if (
                abs(item[0] - ev[0]) < 0.05
                and abs(item[1] - ev[1]) < 0.15
                and item[2] == ev[2]
                and item[3] == ev[3]
            ):
                long_match += 1
                break

    return DiffCompareResult(
        difficulty=difficulty,
        cn_taps=len(cn_taps),
        eve_taps=len(eve_taps),
        cn_longs=len(cn_longs),
        eve_longs=len(eve_longs),
        tap_multiset_match=multiset_ok,
        long_match=long_match,
        long_total=max(len(cn_longs), len(eve_longs)),
    )


def find_arcade_song_dir(base: Path, music_id: int) -> Optional[Path]:
    prefix = f"{music_id}_"
    matches = [d for d in base.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    if not matches:
        for d in base.iterdir():
            if not d.is_dir():
                continue
            nested = [c for c in d.iterdir() if c.is_dir() and c.name.startswith(prefix)]
            matches.extend(nested)
    if not matches:
        return None
    with_eve = [m for m in matches if any(m.glob("*.eve"))]
    if not with_eve:
        for m in matches:
            for child in m.iterdir():
                if child.is_dir() and any(child.glob("*.eve")):
                    with_eve.append(child)
    pool = with_eve or matches
    return sorted(pool, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def resolve_eve_for_diff(song_dir: Path, difficulty: str) -> Optional[Path]:
    prefix = _DIFF_PREFIX[difficulty.upper()]
    candidates = sorted(song_dir.glob(f"{prefix}*.eve"))
    return candidates[0] if candidates else None


def compare_song(
    music_id: int,
    *,
    cn_root: Path,
    arcade_output: Path,
    title: str = "",
) -> SongCompareResult:
    index = CnBundleIndex.scan(cn_root, load_song_list=True)
    cn_available = music_id in index.chart_bundle_by_id
    arcade_dir = find_arcade_song_dir(arcade_output, music_id)
    if not title:
        title = index.get_song_info(music_id).get("name", str(music_id))

    diffs: List[DiffCompareResult] = []
    if cn_available and arcade_dir:
        bundle = index.chart_bundle_by_id[music_id]
        midi_bytes = _extract_text_asset(bundle, str(music_id))
        for diff in ("BSC", "ADV", "EXT"):
            eve_path = resolve_eve_for_diff(arcade_dir, diff)
            if not midi_bytes or not eve_path:
                continue
            cn_taps, cn_longs = parse_cn_midi_bytes(midi_bytes, diff)
            eve_taps, eve_longs = parse_eve_chart(eve_path)
            diffs.append(compare_difficulty(cn_taps, cn_longs, eve_taps, eve_longs, diff))

    return SongCompareResult(
        music_id=music_id,
        title=title,
        cn_available=cn_available,
        arcade_dir=arcade_dir,
        difficulties=diffs,
    )


def format_compare_report(results: Iterable[SongCompareResult]) -> str:
    lines: List[str] = []
    lines.append("国服 MIDI vs 街机 EVE 对照报告")
    lines.append("")
    lines.append("编码规律：note=36+pos；tap=vel127；long=vel127 tail=vel-1")
    lines.append("")
    for res in results:
        lines.append(f"## {res.music_id} {res.title}")
        if not res.cn_available:
            lines.append("  国服：无谱面")
            continue
        if not res.arcade_dir:
            lines.append("  街机：未解包（请先在街机曲库提取）")
            continue
        for d in res.difficulties:
            tap_ok = "OK" if d.tap_multiset_match else "DIFF"
            long_ok = f"{d.long_match}/{d.long_total}"
            lines.append(
                f"  {d.difficulty}: tap {d.cn_taps}/{d.eve_taps} [{tap_ok}]  "
                f"long {d.cn_longs}/{d.eve_longs} [{long_ok}]"
            )
        lines.append("")
    return "\n".join(lines)
