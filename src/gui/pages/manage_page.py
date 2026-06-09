"""
管理页面 — 解包歌曲列表、资源预览、搜索筛选
"""

from pathlib import Path

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtGui import QStandardItemModel, QStandardItem, QPixmap, QIcon
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    ScrollArea, PushButton, LineEdit, TableView,
    FluentIcon as FIcon, CardWidget, BodyLabel, ComboBox,
)

from ...core.malody_writer import parse_song_info
from ...core.song_resources import summarize_resources
from ...core.unpacker import resolve_bpm, resolve_display_title
from ..common.signal_bus import signalBus
from ..common.config import cfg


class SongTableProxy(QSortFilterProxyModel):
    """支持曲名搜索 + 难度筛选的表格代理模型。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._difficulty = "全部"

    def set_difficulty_filter(self, difficulty: str) -> None:
        self._difficulty = difficulty
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not super().filterAcceptsRow(source_row, source_parent):
            return False
        if self._difficulty == "全部":
            return True

        model = self.sourceModel()
        col = {"BSC": 4, "ADV": 5, "EXT": 6}.get(self._difficulty)
        if col is None:
            return True
        level = model.item(source_row, col)
        if not level:
            return False
        text = level.text().strip()
        return text not in ("", "-")


class ManagePage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("managePage")
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(
            ["曲名", "Music ID", "艺术家", "BPM", "BSC", "ADV", "EXT", "音频", "谱面", "路径"]
        )
        self._proxy = SongTableProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        c = QWidget()
        lo = QVBoxLayout(c)
        lo.setContentsMargins(36, 20, 36, 20)
        lo.setSpacing(16)

        tb = CardWidget(c)
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(20, 12, 20, 12)
        self.search_edit = LineEdit(tb)
        self.search_edit.setPlaceholderText("搜索曲名、艺术家或 ID...")
        self.search_edit.setClearButtonEnabled(True)
        self.diff_filter = ComboBox(tb)
        self.diff_filter.addItems(["全部", "BSC", "ADV", "EXT"])
        self.load_btn = PushButton(FIcon.FOLDER, "加载目录", tb)
        self.refresh_btn = PushButton(FIcon.SYNC, "刷新", tb)
        tl.addWidget(BodyLabel("搜索:"))
        tl.addWidget(self.search_edit, 1)
        tl.addWidget(BodyLabel("难度:"))
        tl.addWidget(self.diff_filter)
        tl.addWidget(self.load_btn)
        tl.addWidget(self.refresh_btn)
        lo.addWidget(tb)

        hint = BodyLabel("单击行 → 预览谱面；双击行 → 发送到转换页")
        hint.setStyleSheet("color: gray;")
        lo.addWidget(hint)

        self.table = TableView(c)
        self.table.setModel(self._proxy)
        self.table.setSortingEnabled(True)
        self.table.setMinimumHeight(400)
        self.table.setColumnHidden(9, True)
        self.table.setColumnWidth(0, 220)
        lo.addWidget(self.table, 1)

        self.setWidget(c)

    def _connect_signals(self):
        self.search_edit.textChanged.connect(self._proxy.setFilterFixedString)
        self.diff_filter.currentTextChanged.connect(self._proxy.set_difficulty_filter)
        self.load_btn.clicked.connect(self._load_dir)
        self.refresh_btn.clicked.connect(self._refresh)
        self.table.clicked.connect(self._on_click)
        self.table.doubleClicked.connect(self._on_double_click)
        signalBus.unpack_finished.connect(self._load_dir)

    def _load_dir(self, dir_path: str = ""):
        if not dir_path:
            dir_path = cfg.last_output_dir
        if not dir_path:
            dir_path = QFileDialog.getExistingDirectory(self, "选择歌曲目录")
        if not dir_path:
            return

        base = Path(dir_path)
        if not base.is_dir():
            return

        cfg.last_output_dir = str(base)
        self._model.removeRows(0, self._model.rowCount())

        for song_dir in sorted(base.iterdir()):
            if not song_dir.is_dir():
                continue
            info_path = song_dir / "song_info.txt"
            if not info_path.exists():
                continue

            info = parse_song_info(info_path)
            resources = summarize_resources(song_dir, info)
            levels = info.get("levels", {})
            display_name = resolve_display_title(info) or info.get("name") or song_dir.name
            artist = info.get("artist") or info.get("artist_name") or ""
            bpm = resolve_bpm(info) or info.get("bpm_max") or info.get("bpm") or ""

            name_item = QStandardItem(display_name)
            name_item.setData(str(song_dir), Qt.ItemDataRole.UserRole)
            if resources["has_jacket"] and resources["jacket_path"]:
                pixmap = QPixmap(str(resources["jacket_path"]))
                if not pixmap.isNull():
                    icon = QIcon(pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
                    name_item.setIcon(icon)

            audio_text = "✓" if resources["has_audio"] else "—"
            if resources["has_wav"]:
                audio_text = "WAV"

            row = [
                name_item,
                QStandardItem(info.get("music_id", "")),
                QStandardItem(artist),
                QStandardItem(str(bpm)),
                QStandardItem(levels.get("BSC", "-")),
                QStandardItem(levels.get("ADV", "-")),
                QStandardItem(levels.get("EXT", "-")),
                QStandardItem(audio_text),
                QStandardItem(resources["eve_summary"]),
                QStandardItem(str(song_dir)),
            ]
            for item in row:
                item.setEditable(False)
            self._model.appendRow(row)

        signalBus.song_list_refreshed.emit()

    def _refresh(self):
        self._load_dir()

    def _song_dir_from_index(self, index) -> str:
        src = self._proxy.mapToSource(index)
        path_item = self._model.item(src.row(), 0)
        if path_item:
            song_dir = path_item.data(Qt.ItemDataRole.UserRole)
            if song_dir:
                return song_dir
        return self._model.item(src.row(), 9).text()

    def _on_click(self, index):
        song_dir = self._song_dir_from_index(index)
        if not song_dir:
            return
        difficulty = self.diff_filter.currentText()
        if difficulty == "全部":
            difficulty = "EXT"
        signalBus.chart_loaded.emit({"song_dir": song_dir, "difficulty": difficulty})

    def _on_double_click(self, index):
        song_dir = self._song_dir_from_index(index)
        if song_dir:
            signalBus.song_selected.emit(song_dir)
