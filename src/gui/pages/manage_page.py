"""
管理页面 — 歌曲列表、搜索、筛选
"""

from pathlib import Path

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    ScrollArea, PushButton, LineEdit, TableView,
    FluentIcon as FIcon, CardWidget, BodyLabel, ComboBox,
    InfoBar, InfoBarPosition,
)

from ...core.malody_writer import parse_song_info
from ..common.signal_bus import signalBus
from ..common.config import cfg


class ManagePage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("managePage")
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(["曲名", "Music ID", "BPM", "BSC", "ADV", "EXT", "路径"])
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        c = QWidget()
        lo = QVBoxLayout(c)
        lo.setContentsMargins(36, 20, 36, 20)
        lo.setSpacing(16)

        # 工具栏
        tb = CardWidget(c)
        tl = QHBoxLayout(tb); tl.setContentsMargins(20, 12, 20, 12)
        self.search_edit = LineEdit(tb)
        self.search_edit.setPlaceholderText("搜索曲名或 ID...")
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

        # 歌曲表格
        self.table = TableView(c)
        self.table.setModel(self._proxy)
        self.table.setSortingEnabled(True)
        self.table.setMinimumHeight(400)
        # 隐藏路径列
        self.table.setColumnHidden(6, True)
        lo.addWidget(self.table, 1)

        self.setWidget(c)

    def _connect_signals(self):
        self.search_edit.textChanged.connect(self._proxy.setFilterFixedString)
        self.load_btn.clicked.connect(self._load_dir)
        self.refresh_btn.clicked.connect(self._refresh)
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

        self._model.removeRows(0, self._model.rowCount())
        for song_dir in sorted(base.iterdir()):
            info_path = song_dir / "song_info.txt"
            if not info_path.exists():
                continue
            info = parse_song_info(info_path)
            levels = info.get("levels", {})
            row = [
                QStandardItem(info.get("name", song_dir.name)),
                QStandardItem(info.get("music_id", "")),
                QStandardItem(str(info.get("bpm", ""))),
                QStandardItem(levels.get("BSC", "-")),
                QStandardItem(levels.get("ADV", "-")),
                QStandardItem(levels.get("EXT", "-")),
                QStandardItem(str(song_dir)),
            ]
            self._model.appendRow(row)

        signalBus.song_list_refreshed.emit()

    def _refresh(self):
        self._load_dir()

    def _on_double_click(self, index):
        path_idx = self._proxy.mapToSource(index).siblingAtColumn(6)
        song_dir = path_idx.data()
        if song_dir:
            signalBus.song_selected.emit(song_dir)
