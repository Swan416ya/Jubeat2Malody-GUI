"""
国服 MIDI 谱面解析 — 转为 jubeatools Song 对象。

国服谱面为标准 MIDI，每难度一轨（bsc/adv/ext），音符 36–51 对应 16 面板。
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jubeatools import song

_MIDI_DIFF = {"bsc": "BSC", "adv": "ADV", "ext": "EXT"}
_PANEL_NOTE_BASE = 36
_TAP_VELOCITIES = frozenset({127, 100})
# 国服 MIDI 两种编码（对照街机 EVE + 国服独占曲验证）：
# A) 经典：note_on + note_off，单击 velocity=127，长按 velocity!=127 且 tail=velocity-1
# B) 独占/新曲：仅 note_on，单击 velocity=100（无 note_off）


def _track_name(track) -> str:
    for msg in track:
        if msg.type == "track_name":
            return msg.name.strip("\x00").lower()
    return ""


def _ticks_to_beat(ticks: int, ticks_per_beat: int) -> Fraction:
    return Fraction(ticks, ticks_per_beat)


def _panel_index(note: int) -> Optional[int]:
    pos_idx = note - _PANEL_NOTE_BASE
    if 0 <= pos_idx < 16:
        return pos_idx
    return None


def _track_uses_note_off(track) -> bool:
    for msg in track:
        if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            return True
    return False


def _parse_note_on_only_track(
    track,
    ticks_per_beat: int,
) -> Tuple[List[song.TapNote], List[song.LongNote]]:
    abs_tick = 0
    taps: List[song.TapNote] = []
    for msg in track:
        abs_tick += msg.time
        if msg.type != "note_on" or msg.velocity <= 0:
            continue
        pos_idx = _panel_index(msg.note)
        if pos_idx is None:
            continue
        if msg.velocity not in _TAP_VELOCITIES:
            continue
        taps.append(
            song.TapNote(
                time=_ticks_to_beat(abs_tick, ticks_per_beat),
                position=song.NotePosition.from_index(pos_idx),
            )
        )
    return taps, []


def _parse_paired_note_track(
    track,
    ticks_per_beat: int,
) -> Tuple[List[song.TapNote], List[song.LongNote]]:
    abs_tick = 0
    active: Dict[int, Tuple[int, int]] = {}
    taps: List[song.TapNote] = []
    longs: List[song.LongNote] = []

    def close_note(note: int, end_tick: int) -> None:
        start = active.pop(note, None)
        if start is None:
            return
        start_tick, velocity = start
        duration = end_tick - start_tick
        pos_idx = _panel_index(note)
        if pos_idx is None:
            return
        position = song.NotePosition.from_index(pos_idx)
        start_beat = _ticks_to_beat(start_tick, ticks_per_beat)

        if velocity in _TAP_VELOCITIES:
            taps.append(song.TapNote(time=start_beat, position=position))
            return

        tail_idx = velocity - 1
        if tail_idx < 0 or tail_idx >= 16:
            taps.append(song.TapNote(time=start_beat, position=position))
            return
        longs.append(
            song.LongNote(
                time=start_beat,
                position=position,
                duration=_ticks_to_beat(duration, ticks_per_beat),
                tail_tip=song.NotePosition.from_index(tail_idx),
            )
        )

    for msg in track:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = (abs_tick, msg.velocity)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            close_note(msg.note, abs_tick)

    return taps, longs


def _parse_difficulty_track(
    track,
    ticks_per_beat: int,
) -> Tuple[List[song.TapNote], List[song.LongNote]]:
    if _track_uses_note_off(track):
        return _parse_paired_note_track(track, ticks_per_beat)
    return _parse_note_on_only_track(track, ticks_per_beat)


def _make_timing(bpm: float, beat: Fraction = Fraction(0, 1)) -> song.Timing:
    return song.Timing(
        events=[song.BPMEvent(time=beat, BPM=Decimal(str(bpm)))],
        beat_zero_offset=Decimal("0"),
    )


def _build_timing(midi_file, info: Optional[dict] = None) -> song.Timing:
    bpm = None
    if info:
        for key in ("bpm_max", "bpm_min", "bpm"):
            val = info.get(key)
            if val:
                try:
                    bpm = float(val)
                    break
                except (TypeError, ValueError):
                    pass

    for track in midi_file.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                bpm = 60_000_000 / msg.tempo
                beat = _ticks_to_beat(abs_tick, midi_file.ticks_per_beat)
                return _make_timing(bpm, beat)

    if bpm is None:
        bpm = 120.0
    return _make_timing(bpm)


def load_cn_chart(midi_path: Path, beat_snap: int = 4) -> song.Chart:
    import mido

    midi = mido.MidiFile(str(midi_path))
    track_name = ""
    target = None
    for track in midi.tracks:
        track_name = _track_name(track)
        if track_name in _MIDI_DIFF:
            target = track
            break
    if target is None:
        target = midi.tracks[-1]

    taps, longs = _parse_difficulty_track(target, midi.ticks_per_beat)
    notes: List[song.TapNote | song.LongNote] = list(taps) + list(longs)
    notes.sort(key=lambda n: (float(n.time), 0 if isinstance(n, song.TapNote) else 1))
    timing = _build_timing(midi)
    return song.Chart(notes=notes, timing=timing)


def load_cn_song(directory: Path, beat_snap: int = 4) -> song.Song:
    """从国服解包目录加载 bsc/adv/ext.mid，返回 jubeatools Song。"""
    info: dict = {}
    info_path = directory / "song_info.txt"
    if info_path.is_file():
        from .malody_writer import parse_song_info

        info = parse_song_info(info_path)

    charts: Dict[str, song.Chart] = {}
    timing: Optional[song.Timing] = None

    for stem, diff in _MIDI_DIFF.items():
        midi_path = directory / f"{stem}.mid"
        if not midi_path.is_file():
            continue
        chart = load_cn_chart(midi_path, beat_snap=beat_snap)
        charts[diff] = chart
        if timing is None and chart.timing:
            timing = chart.timing

    if not charts:
        chart_path = directory / "chart.mid"
        if chart_path.is_file():
            import mido

            midi = mido.MidiFile(str(chart_path))
            for track in midi.tracks:
                name = _track_name(track)
                diff = _MIDI_DIFF.get(name)
                if not diff:
                    continue
                taps, longs = _parse_difficulty_track(track, midi.ticks_per_beat)
                notes = list(taps) + list(longs)
                notes.sort(key=lambda n: (float(n.time), 0 if isinstance(n, song.TapNote) else 1))
                t = _build_timing(midi, info)
                charts[diff] = song.Chart(notes=notes, timing=t)
                if timing is None:
                    timing = t

    if not charts:
        raise FileNotFoundError("未找到国服 MIDI 谱面")

    common_timing = timing or _make_timing(120.0)
    instances = []
    for diff, chart in charts.items():
        instances.append(
            song.Song(metadata=song.Metadata(), charts={diff: chart}, common_timing=common_timing)
        )
    return song.Song.from_monochart_instances(*instances)
