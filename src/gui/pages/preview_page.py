"""
预览页面 — 4×4 网格可视化谱面，BGM 同步播放
参考 jubeatnet Pattern 编码: 0=空, 1=点击, 2=长按起始, 3=长按持续
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRectF, QThread, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    ScrollArea, PushButton, BodyLabel, ComboBox,
    FluentIcon as FIcon, CardWidget, Slider, StrongBodyLabel,
)

from ...core.eve_parser import load_chart_info, ChartInfo
from ...core.song_resources import (
    DIFFICULTIES, build_beat_to_seconds, ensure_playable_audio, resolve_eve_path,
)
from ..common.audio_player import ChartAudioPlayer
from ..common.signal_bus import signalBus
from ..common.config import cfg


class AudioPrepareWorker(QThread):
    """后台准备可播放音频（bgm.bin ADPCM 解码可能较慢）。"""

    finished = Signal(object)

    def __init__(self, song_dir: Path, parent=None):
        super().__init__(parent)
        self.song_dir = song_dir

    def run(self):
        try:
            path = ensure_playable_audio(self.song_dir)
        except Exception:
            path = None
        self.finished.emit(path)


class ChartGridWidget(QWidget):
    """4×4 谱面网格可视化组件"""

    COLOR_EMPTY = QColor(45, 45, 45)
    COLOR_TAP = QColor(0, 120, 212)
    COLOR_LONG_START = QColor(255, 140, 0)
    COLOR_LONG_HOLD = QColor(255, 200, 80)
    COLOR_TEXT = QColor(255, 255, 255)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = [[0] * 4 for _ in range(4)]
        self.setMinimumSize(280, 280)

    def set_grid(self, grid: list):
        self._grid = grid
        self.update()

    def clear(self):
        self._grid = [[0] * 4 for _ in range(4)]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cell_w, cell_h = w / 4, h / 4
        margin = 3

        for row in range(4):
            for col in range(4):
                x, y = col * cell_w, row * cell_h
                val = self._grid[row][col]
                color = {
                    0: self.COLOR_EMPTY, 1: self.COLOR_TAP,
                    2: self.COLOR_LONG_START, 3: self.COLOR_LONG_HOLD,
                }.get(val, self.COLOR_EMPTY)

                rect = QRectF(x + margin, y + margin, cell_w - 2 * margin, cell_h - 2 * margin)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(rect, 8, 8)

                if val > 0:
                    painter.setPen(QPen(self.COLOR_TEXT))
                    painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
                    painter.drawText(rect, Qt.AlignCenter, str(row * 4 + col))
        painter.end()


class PreviewPage(ScrollArea):
    """预览页面 — 谱面可视化 + BGM 同步播放"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewPage")
        self._chart: ChartInfo | None = None
        self._song_dir: Path | None = None
        self._time_frames: list[tuple[float, list]] = []
        self._end_time = 0.0
        self._playing = False
        self._virtual_time = 0.0
        self._audio_worker: AudioPrepareWorker | None = None
        self._pending_play = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._audio = ChartAudioPlayer(self)
        self._audio.media_ready.connect(self._on_audio_ready)
        self._audio.media_error.connect(self._on_audio_error)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)

        file_card = CardWidget(container)
        fl = QHBoxLayout(file_card)
        fl.setContentsMargins(20, 16, 20, 16)
        fl.addWidget(BodyLabel("谱面来源:"))
        self.eve_path_label = StrongBodyLabel("未加载")
        self.eve_path_label.setStyleSheet("color: gray;")
        fl.addWidget(self.eve_path_label, 1)
        self.load_btn = PushButton(FIcon.FOLDER, "打开 EVE", file_card)
        self.load_song_btn = PushButton(FIcon.MUSIC, "打开歌曲目录", file_card)
        fl.addWidget(self.load_btn)
        fl.addWidget(self.load_song_btn)
        layout.addWidget(file_card)

        info_card = CardWidget(container)
        il = QHBoxLayout(info_card)
        il.setContentsMargins(20, 16, 20, 16)
        self.bpm_label = BodyLabel("BPM: --")
        self.notes_label = BodyLabel("音符数: --")
        self.audio_label = BodyLabel("音频: --")
        self.time_label = BodyLabel("0:00 / 0:00")
        self.diff_combo = ComboBox(info_card)
        self.diff_combo.addItems(list(DIFFICULTIES))
        self.diff_combo.setCurrentText("EXT")
        il.addWidget(self.bpm_label)
        il.addWidget(self.notes_label)
        il.addWidget(self.audio_label)
        il.addWidget(self.time_label)
        il.addStretch(1)
        il.addWidget(BodyLabel("难度:"))
        il.addWidget(self.diff_combo)
        layout.addWidget(info_card)

        self.grid_widget = ChartGridWidget(container)
        self.grid_widget.setMinimumHeight(320)
        layout.addWidget(self.grid_widget, 1)

        ctrl_card = CardWidget(container)
        cl = QHBoxLayout(ctrl_card)
        cl.setContentsMargins(20, 16, 20, 16)
        self.play_btn = PushButton(FIcon.PLAY, "播放", ctrl_card)
        self.pause_btn = PushButton(FIcon.PAUSE, "暂停", ctrl_card)
        self.stop_btn = PushButton(FIcon.CANCEL, "停止", ctrl_card)
        self.pause_btn.setDisabled(True)
        self.stop_btn.setDisabled(True)
        cl.addWidget(self.play_btn)
        cl.addWidget(self.pause_btn)
        cl.addWidget(self.stop_btn)
        cl.addStretch(1)
        cl.addWidget(BodyLabel("速度:"))
        self.speed_slider = Slider(Qt.Horizontal, ctrl_card)
        self.speed_slider.setRange(25, 300)
        self.speed_slider.setValue(int(cfg.preview_speed * 100))
        self.speed_label = BodyLabel(f"{cfg.preview_speed:.1f}x")
        cl.addWidget(self.speed_slider)
        cl.addWidget(self.speed_label)
        layout.addWidget(ctrl_card)

        layout.addStretch(1)
        self.setWidget(container)

    def _connect_signals(self):
        self.load_btn.clicked.connect(self._load_eve)
        self.load_song_btn.clicked.connect(self._pick_song_dir)
        self.play_btn.clicked.connect(self._play)
        self.pause_btn.clicked.connect(self._pause)
        self.stop_btn.clicked.connect(self._stop)
        self.speed_slider.valueChanged.connect(self._on_speed_change)
        self.diff_combo.currentTextChanged.connect(self._on_difficulty_changed)
        signalBus.chart_loaded.connect(self._on_chart_loaded)
        signalBus.song_selected.connect(self._on_song_selected)

    def _pick_song_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择解包后的歌曲目录")
        if path:
            self._load_song_dir(Path(path), self.diff_combo.currentText())

    def _load_eve(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 EVE 谱面文件", "", "EVE Files (*.eve);;All Files (*)"
        )
        if path:
            self._song_dir = Path(path).parent
            self._load_chart(path)

    def _on_song_selected(self, song_dir: str):
        self._load_song_dir(Path(song_dir), self.diff_combo.currentText())

    def _on_chart_loaded(self, data: dict):
        if data.get("song_dir"):
            difficulty = data.get("difficulty", "EXT")
            if difficulty == "全部":
                difficulty = "EXT"
            self._load_song_dir(Path(data["song_dir"]), difficulty)
        elif data.get("path"):
            self._song_dir = Path(data["path"]).parent
            self._load_chart(data["path"])

    def _on_difficulty_changed(self, difficulty: str):
        if self._song_dir:
            self._load_song_dir(self._song_dir, difficulty)

    def _load_song_dir(self, song_dir: Path, difficulty: str):
        self._song_dir = song_dir
        self.diff_combo.blockSignals(True)
        self.diff_combo.setCurrentText(difficulty)
        self.diff_combo.blockSignals(False)

        eve_path = resolve_eve_path(song_dir, difficulty)
        if not eve_path:
            self.eve_path_label.setText(f"{song_dir.name} — 未找到 {difficulty} 谱面")
            self.eve_path_label.setStyleSheet("color: red;")
            return

        self._prepare_audio(song_dir)
        self._load_chart(str(eve_path))

    def _prepare_audio(self, song_dir: Path) -> None:
        if self._audio_worker and self._audio_worker.isRunning():
            self._audio_worker.finished.disconnect()
            self._audio_worker.wait(200)

        self._audio.stop()
        self.audio_label.setText("音频: 准备中...")
        self.time_label.setText("0:00 / 0:00")
        self.play_btn.setDisabled(True)

        self._audio_worker = AudioPrepareWorker(song_dir, self)
        self._audio_worker.finished.connect(self._on_audio_prepared)
        self._audio_worker.start()

    def _on_audio_prepared(self, audio_path):
        if self.sender() is not self._audio_worker:
            return
        if not audio_path:
            self.audio_label.setText("音频: 未找到")
            self.play_btn.setEnabled(bool(self._time_frames))
            return
        path = Path(audio_path)
        self._audio.load(path)
        self.audio_label.setText(f"音频: {path.name}（加载中）")
        if self._pending_play and self._audio.is_ready():
            self._start_playback()

    def _on_audio_ready(self) -> None:
        duration = self._audio.duration_ms()
        loaded = self._audio.loaded_path
        self.audio_label.setText(f"音频: {loaded.name if loaded else '已就绪'}")
        self._update_time_label(self._audio.position_ms(), duration)
        self.play_btn.setEnabled(bool(self._time_frames))
        if self._pending_play:
            self._start_playback()

    def _on_audio_error(self, message: str) -> None:
        self.audio_label.setText(f"音频: {message}")
        self.play_btn.setEnabled(bool(self._time_frames))

    @staticmethod
    def _format_time(ms: int) -> str:
        total_sec = max(0, ms) // 1000
        return f"{total_sec // 60}:{total_sec % 60:02d}"

    def _update_time_label(self, pos_ms: int, dur_ms: int | None = None) -> None:
        if dur_ms is None:
            dur_ms = self._audio.duration_ms()
        self.time_label.setText(
            f"{self._format_time(pos_ms)} / {self._format_time(dur_ms)}"
        )

    def _load_chart(self, path: str):
        try:
            self._stop()
            self._chart = load_chart_info(Path(path))
            eve_path = Path(path)
            if self._song_dir:
                self.eve_path_label.setText(f"{self._song_dir.name} / {eve_path.name}")
            else:
                self.eve_path_label.setText(eve_path.name)
            self.eve_path_label.setStyleSheet("color: white;")

            bpms = [bpm for _, bpm in self._chart.bpms]
            if len(bpms) > 1:
                bpm_min, bpm_max = min(bpms), max(bpms)
                bpm_str = (
                    f"BPM: {bpm_min:.1f}-{bpm_max:.1f}"
                    if bpm_min != bpm_max else f"BPM: {bpm_min:.1f}"
                )
            elif bpms:
                bpm_str = f"BPM: {bpms[0]:.1f}"
            else:
                bpm_str = "BPM: Unknown"
            self.bpm_label.setText(bpm_str)
            self.notes_label.setText(f"音符数: {self._chart.note_count}")
            self._build_frames()
            self._render_at_time(0.0)
        except Exception as e:
            self.eve_path_label.setText(f"加载失败: {e}")
            self.eve_path_label.setStyleSheet("color: red;")

    def _build_frames(self):
        """按 beat 时间构建带时间戳的网格帧序列。"""
        if not self._chart:
            return

        bpms = self._chart.bpms
        default_bpm = bpms[0][1] if bpms else 120.0
        beat_to_sec = build_beat_to_seconds(bpms, default_bpm)

        events = []
        for beat, pos in self._chart.tap_notes:
            events.append((beat, pos, "tap"))
        for beat, pos, end_beat, end_pos in self._chart.long_notes:
            events.append((beat, pos, "long_start"))
            events.append((end_beat, end_pos, "long_end"))
        events.sort(key=lambda e: float(e[0]))

        if not events:
            self._time_frames = []
            self._end_time = 0.0
            return

        long_active: dict[int, bool] = {}
        self._time_frames = []
        beat_times = sorted(set(e[0] for e in events))

        for beat_time in beat_times:
            for beat, pos, kind in events:
                if beat != beat_time:
                    continue
                if kind == "long_start":
                    long_active[pos] = True
                elif kind == "long_end":
                    long_active.pop(pos, None)

            grid = [[0] * 4 for _ in range(4)]
            for pos in long_active:
                r, c = pos // 4, pos % 4
                grid[r][c] = 3

            for beat, pos, kind in events:
                if beat != beat_time:
                    continue
                r, c = pos // 4, pos % 4
                if kind == "tap":
                    grid[r][c] = 1
                elif kind == "long_start":
                    grid[r][c] = 2

            t = beat_to_sec(float(beat_time))
            self._time_frames.append((t, [row[:] for row in grid]))

        self._end_time = self._time_frames[-1][0] + 2.0

    def _render_at_time(self, time_sec: float):
        if not self._time_frames:
            self.grid_widget.clear()
            return
        frame = self._time_frames[0][1]
        for t, grid in self._time_frames:
            if t <= time_sec:
                frame = grid
            else:
                break
        self.grid_widget.set_grid(frame)

    def _play(self):
        if not self._time_frames:
            return
        self._pending_play = True
        if self._audio.is_ready():
            self._start_playback()
        elif self._audio.is_loaded():
            self.play_btn.setDisabled(True)
        else:
            self.play_btn.setDisabled(True)

    def _start_playback(self) -> None:
        if not self._time_frames:
            self._pending_play = False
            return
        self._pending_play = False
        self._playing = True
        self._virtual_time = 0.0
        self.play_btn.setDisabled(True)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        speed = cfg.preview_speed
        self._audio.set_playback_rate(speed)
        self._audio.stop()
        self._audio.play(0)
        self._render_at_time(0.0)
        self._timer.start()

    def _pause(self):
        self._playing = False
        self._pending_play = False
        self._timer.stop()
        self.play_btn.setEnabled(True)
        self.pause_btn.setDisabled(True)
        self._audio.pause()

    def _stop(self):
        self._playing = False
        self._pending_play = False
        self._timer.stop()
        self._virtual_time = 0.0
        self._audio.stop()
        self._render_at_time(0.0)
        self._update_time_label(0)
        self.play_btn.setEnabled(bool(self._time_frames))
        self.pause_btn.setDisabled(True)
        self.stop_btn.setDisabled(True)

    def _tick(self):
        if not self._time_frames or not self._playing:
            return

        if self._audio.is_ready():
            pos_ms = self._audio.position_ms()
            pos_sec = pos_ms / 1000.0
            self._render_at_time(pos_sec)
            self._update_time_label(pos_ms)
            if pos_ms >= max(0, self._audio.duration_ms() - 80):
                self._stop()
            return

        interval = self._timer.interval() / 1000.0
        self._virtual_time += interval * cfg.preview_speed
        self._render_at_time(self._virtual_time)
        self._update_time_label(int(self._virtual_time * 1000), int(self._end_time * 1000))
        if self._virtual_time >= self._end_time:
            self._stop()

    def _on_speed_change(self, val: int):
        speed = val / 100.0
        cfg.preview_speed = speed
        self.speed_label.setText(f"{speed:.1f}x")
        if self._playing:
            self._audio.set_playback_rate(speed)
