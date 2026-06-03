"""
EVE 谱面解析模块

解析 Jubeat EVE 格式谱面文件，转换为内部数据结构。
依赖: jubeatools (长按音符解析)
"""

from pathlib import Path
from fractions import Fraction
from dataclasses import dataclass, field
from typing import List, Optional
from collections import Counter


@dataclass
class BPMChange:
    beat: Fraction
    bpm: float


@dataclass
class TapNote:
    beat: Fraction
    position: int  # 0-15


@dataclass
class LongNote:
    beat: Fraction
    position: int  # 0-15
    end_beat: Fraction
    end_position: int  # 0-15


@dataclass
class EVEChart:
    bpm_changes: List[BPMChange] = field(default_factory=list)
    tap_notes: List[TapNote] = field(default_factory=list)
    long_notes: List[LongNote] = field(default_factory=list)
    ticks_per_beat: int = 0


@dataclass
class EVEEvent:
    tick: int
    command: str
    value: int


def parse_eve_file(filepath: Path) -> EVEChart:
    """解析 EVE 谱面文件，返回 EVEChart 数据结构"""
    chart = EVEChart()
    events: List[EVEEvent] = []

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) != 3:
                continue
            try:
                tick = int(parts[0])
                command = parts[1].strip()
                value = int(parts[2])
                events.append(EVEEvent(tick, command, value))
            except (ValueError, IndexError):
                continue

    if not events:
        return chart

    # 从 HAKU 事件计算 ticks_per_beat
    haku_ticks = [e.tick for e in events if e.command == 'HAKU']
    if len(haku_ticks) >= 2:
        intervals = [haku_ticks[i] - haku_ticks[i - 1]
                     for i in range(1, len(haku_ticks))
                     if haku_ticks[i] - haku_ticks[i - 1] > 0]
        if intervals:
            chart.ticks_per_beat = Counter(intervals).most_common(1)[0][0]

    if chart.ticks_per_beat == 0:
        chart.ticks_per_beat = 92  # fallback

    tpb = chart.ticks_per_beat

    # 解析 TEMPO 事件
    for e in events:
        if e.command == 'TEMPO':
            bpm = e.value / 1000.0
            beat = Fraction(e.tick, tpb)
            chart.bpm_changes.append(BPMChange(beat=beat, bpm=bpm))

    # 解析 PLAY 事件 (tap notes)
    for e in events:
        if e.command == 'PLAY':
            beat = Fraction(e.tick, tpb)
            chart.tap_notes.append(TapNote(beat=beat, position=e.value))

    # 使用 jubeatools 解析长按音符
    try:
        from jubeatools.formats.konami.eve.load import load_eve as jt_load_eve
        from jubeatools.song import LongNote as JTLongNote

        jt_song = jt_load_eve(filepath)
        for _, jt_chart in jt_song.charts.items():
            for note in jt_chart.notes:
                if isinstance(note, JTLongNote):
                    pos = note.position.y * 4 + note.position.x
                    end_pos = note.tail_tip.y * 4 + note.tail_tip.x
                    chart.long_notes.append(LongNote(
                        beat=note.time,
                        position=pos,
                        end_beat=note.time + note.duration,
                        end_position=end_pos
                    ))
    except Exception:
        pass  # 长按音符解析失败不影响基本功能

    return chart
