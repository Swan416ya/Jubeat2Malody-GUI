"""
国服 MIDI 谱面解析 — 转为 jubeatools Song 对象。

国服谱面为标准 MIDI，每难度一轨（bsc/adv/ext），音符 36–51 对应 16 面板。
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional

from jubeatools import song

_MIDI_DIFF = {"bsc": "BSC", "adv": "ADV", "ext": "EXT"}
_PANEL_NOTE_BASE = 36
_HOLD_TICK_THRESHOLD = 360  # >0.75 拍视为 long（国服常见 tap 门长 240 tick）


def _track_name(track) -> str:
    for msg in track:
        if msg.type == "track_name":
            return msg.name.strip("\x00").lower()
    return ""


def _ticks_to_beat(ticks: int, ticks_per_beat: int) -> Fraction:
    return Fraction(ticks, ticks_per_beat)


def _parse_difficulty_track(
    track,
    ticks_per_beat: int,
) -> Tuple[List[song.TapNote], List[song.LongNote]]:
    abs_tick = 0
    active: Dict[int, int] = {}
    taps: List[song.TapNote] = []
    longs: List[song.LongNote] = []

    def close_note(note: int, end_tick: int) -> None:
        start = active.pop(note, None)
        if start is None:
            return
        duration = end_tick - start
        pos_idx = note - _PANEL_NOTE_BASE
        if not (0 <= pos_idx < 16):
            return
        position = song.NotePosition.from_index(pos_idx)
        start_beat = _ticks_to_beat(start, ticks_per_beat)
        if duration >= _HOLD_TICK_THRESHOLD:
            end_beat = _ticks_to_beat(end_tick, ticks_per_beat)
            longs.append(
                song.LongNote(
                    time=start_beat,
                    position=position,
                    duration=end_beat - start_beat,
                    tail_tip=position,
                )
            )
        else:
            taps.append(song.TapNote(time=start_beat, position=position))

    for msg in track:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = abs_tick
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            close_note(msg.note, abs_tick)

    return taps, longs


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
