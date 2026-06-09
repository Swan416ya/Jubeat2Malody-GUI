"""
EVE 谱面解析模块 — 基于 jubeatools

核心逻辑全部复用 jubeatools:
- EVE 事件解析: jubeatools.formats.konami.eve.load
- tick→beat 转换: jubeatools TimeMap (tick→seconds→beats)
- TEMPO→BPM 转换: jubeatools value_to_bpm (微秒/拍 → BPM)
- 长按音符解码: jubeatools EveLong (position/direction/duration 编码)
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple

from jubeatools import song
from jubeatools.formats.konami.eve.load import iter_events, load_eve, load_file
from jubeatools.formats.konami.load_tools import make_chart_from_events

from .song_resources import DIFFICULTIES, resolve_eve_path


# 文件名 → 难度名称映射
FILENAME_TO_DIFFICULTY = {
    "bsc": "BSC",
    "adv": "ADV",
    "ext": "EXT",
    "basic": "BSC",
    "advanced": "ADV",
    "extreme": "EXT",
}


@dataclass
class ChartInfo:
    """谱面预览信息 (GUI 用，与 jubeatools 内部类型解耦)"""
    bpms: List[Tuple[float, float]] = field(default_factory=list)      # [(beat, bpm), ...]
    tap_notes: List[Tuple[float, int]] = field(default_factory=list)   # [(beat, position_index), ...]
    long_notes: List[Tuple[float, int, float, int]] = field(default_factory=list)  # [(beat, pos, end_beat, end_pos), ...]

    @property
    def note_count(self) -> int:
        return len(self.tap_notes) + len(self.long_notes)


def _chart_to_info(chart: song.Chart) -> ChartInfo:
    """将 jubeatools Chart 转换为 GUI 友好的 ChartInfo"""
    info = ChartInfo()

    # BPM 事件
    if chart.timing:
        for ev in chart.timing.events:
            info.bpms.append((float(ev.time), float(ev.BPM)))
    elif chart.timing is None:
        # chart.timing=None 时使用 song.common_timing，由调用方处理
        pass

    # 音符
    for note in chart.notes:
        if isinstance(note, song.TapNote):
            info.tap_notes.append((float(note.time), note.position.index))
        elif isinstance(note, song.LongNote):
            info.long_notes.append((
                float(note.time),
                note.position.index,
                float(note.time + note.duration),
                note.tail_tip.index,
            ))

    return info


def load_eve_chart(eve_path: Path, beat_snap: int = 240) -> song.Chart:
    """加载单个 EVE 文件，返回 jubeatools Chart 对象

    Args:
        eve_path: .eve 文件路径
        beat_snap: 节拍量化精度 (默认 240，即 1/240 拍)
    """
    lines = load_file(eve_path)
    events = list(iter_events(lines))
    return make_chart_from_events(events, beat_snap=beat_snap)


def _load_eve_chart_as_song(eve_path: Path, difficulty: str, beat_snap: int = 240) -> song.Song:
    chart = load_eve_chart(eve_path, beat_snap=beat_snap)
    diff = song.Difficulty(difficulty)
    return song.Song(metadata=song.Metadata(), charts={diff.value: chart})


def load_eve_song(directory: Path, beat_snap: int = 240) -> song.Song:
    """加载目录中各难度 EVE，返回 jubeatools Song 对象。

    每个难度只取一个规范文件（兼容 bsc_2.eve 等 rename_dupes 命名）。
    若无匹配则回退到 jubeatools 默认 glob 行为。
    """
    charts = []
    for difficulty in DIFFICULTIES:
        eve_path = resolve_eve_path(directory, difficulty)
        if eve_path:
            charts.append(_load_eve_chart_as_song(eve_path, difficulty, beat_snap=beat_snap))

    if charts:
        return song.Song.from_monochart_instances(*charts)
    return load_eve(directory, beat_snap=beat_snap)


def load_chart_info(eve_path: Path, beat_snap: int = 240) -> ChartInfo:
    """加载单个 EVE 文件并返回 GUI 友好的 ChartInfo

    用于预览页面等不需要完整 Song 对象的场景。
    """
    chart = load_eve_chart(eve_path, beat_snap=beat_snap)
    info = _chart_to_info(chart)

    # 如果 chart 没有 timing，说明需要从 common_timing 获取
    # 单文件加载时没有 common_timing，此时 BPM 列表为空
    # 但 make_chart_from_events 总是会设置 chart.timing
    return info
