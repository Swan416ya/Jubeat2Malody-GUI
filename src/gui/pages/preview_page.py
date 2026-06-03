"""
预览页面 — 4×4 网格可视化谱面，支持播放动画
参考 jubeatnet Pattern 编码: 0=空, 1=点击, 2=长按起始, 3=长按持续
"""

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    ScrollArea, PushButton, BodyLabel, ComboBox,
    FluentIcon as FIcon, CardWidget, Slider, StrongBodyLabel,
)

from ...core.eve_parser import parse_eve_file, EVEChart
from ..common.signal_bus import signalBus
from ..common.config import cfg


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
    """预览页面 — 谱面可视化 + 播放动画"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewPage")
        self._chart: EVEChart | None = None
        self._frame_idx = 0
        self._frames: list = []
        self._playing = False
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)

        # 文件选择
        file_card = CardWidget(container)
        fl = QHBoxLayout(file_card)
        fl.setContentsMargins(20, 16, 20, 16)
        fl.addWidget(BodyLabel("EVE 谱面文件:"))
        self.eve_path_label = StrongBodyLabel("未加载")
        self.eve_path_label.setStyleSheet("color: gray;")
        fl.addWidget(self.eve_path_label, 1)
        self.load_btn = PushButton(FIcon.FOLDER, "加载", file_card)
        fl.addWidget(self.load_btn)
        layout.addWidget(file_card)

        # 谱面信息
        info_card = CardWidget(container)
        il = QHBoxLayout(info_card)
        il.setContentsMargins(20, 16, 20, 16)
        self.bpm_label = BodyLabel("BPM: --")
        self.notes_label = BodyLabel("音符数: --")
        self.diff_combo = ComboBox(info_card)
        self.diff_combo.addItems(["BSC", "ADV", "EXT"])
        il.addWidget(self.bpm_label)
        il.addWidget(self.notes_label)
        il.addStretch(1)
        il.addWidget(BodyLabel("难度:"))
        il.addWidget(self.diff_combo)
        layout.addWidget(info_card)

        # 4×4 网格
        self.grid_widget = ChartGridWidget(container)
        self.grid_widget.setMinimumHeight(320)
        layout.addWidget(self.grid_widget, 1)

        # 播放控制
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
        self.play_btn.clicked.connect(self._play)
        self.pause_btn.clicked.connect(self._pause)
        self.stop_btn.clicked.connect(self._stop)
        self.speed_slider.valueChanged.connect(self._on_speed_change)
        signalBus.chart_loaded.connect(self._on_chart_loaded)

    def _load_eve(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 EVE 谱面文件", "", "EVE Files (*.eve);;All Files (*)"
        )
        if path:
            self._load_chart(path)

    def _load_chart(self, path: str):
        from pathlib import Path
        try:
            self._chart = parse_eve_file(Path(path))
            self.eve_path_label.setText(Path(path).name)
            self.eve_path_label.setStyleSheet("color: white;")
            bpm = self._chart.bpm_changes[0].bpm if self._chart.bpm_changes else 0
            note_count = len(self._chart.tap_notes) + len(self._chart.long_notes)
            self.bpm_label.setText(f"BPM: {bpm:.1f}")
            self.notes_label.setText(f"音符数: {note_count}")
            self._build_frames()
            self._render_frame(0)
        except Exception as e:
            self.eve_path_label.setText(f"加载失败: {e}")
            self.eve_path_label.setStyleSheet("color: red;")

    def _on_chart_loaded(self, data: dict):
        if "path" in data:
            self._load_chart(data["path"])

    def _build_frames(self):
        """将谱面按时间排序，构建逐帧数据"""
        if not self._chart:
            return
        # 合并所有音符事件，按 beat 排序
        events = []
        for tap in self._chart.tap_notes:
            events.append((tap.beat, tap.position, "tap"))
        for ln in self._chart.long_notes:
            events.append((ln.beat, ln.position, "long_start"))
            events.append((ln.end_beat, ln.end_position, "long_end"))
        events.sort(key=lambda e: float(e[0]))

        # 逐帧: 每个事件对应一帧 4×4 网格快照
        grid = [[0] * 4 for _ in range(4)]
        self._frames = []
        for beat, pos, kind in events:
            row, col = pos // 4, pos % 4
            if kind == "tap":
                grid[row][col] = 1
            elif kind == "long_start":
                grid[row][col] = 2
            elif kind == "long_end":
                grid[row][col] = 0  # 长按结束
            # 深拷贝当前帧
            self._frames.append([r[:] for r in grid])

    def _render_frame(self, idx: int):
        if 0 <= idx < len(self._frames):
            self.grid_widget.set_grid(self._frames[idx])

    def _play(self):
        if not self._frames:
            return
        self._playing = True
        self.play_btn.setDisabled(True)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        signalBus.preview_play.emit()
        self._timer.start()

    def _pause(self):
        self._playing = False
        self._timer.stop()
        self.play_btn.setEnabled(True)
        self.pause_btn.setDisabled(True)
        signalBus.preview_pause.emit()

    def _stop(self):
        self._playing = False
        self._timer.stop()
        self._frame_idx = 0
        self._render_frame(0)
        self.play_btn.setEnabled(True)
        self.pause_btn.setDisabled(True)
        self.stop_btn.setDisabled(True)
        signalBus.preview_stop.emit()

    def _tick(self):
        if self._frame_idx < len(self._frames):
            self._render_frame(self._frame_idx)
            self._frame_idx += 1
        else:
            self._stop()

    def _on_speed_change(self, val: int):
        speed = val / 100.0
        cfg.preview_speed = speed
        self.speed_label.setText(f"{speed:.1f}x")
        interval = max(10, int(50 / speed))
        self._timer.setInterval(interval)
