"""
国服曲库页面 — 浏览 Unity Bundle 曲库，单首解包。
"""

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    ScrollArea, PushButton, LineEdit, ProgressBar,
    TextEdit, FluentIcon as FIcon, CardWidget, BodyLabel,
    InfoBar, InfoBarPosition, TableView, ComboBox, StrongBodyLabel,
)

from ...core.cn_bundles import CnBundleIndex, extract_cn_song, find_cn_hotupdate_dir, is_cn_hotupdate_dir
from ...core.cn_catalog import CnCatalogEntry, scan_cn_catalog
from ...core.cn_catalog_cache import load_cn_catalog_cache, refresh_cn_extracted_status, save_cn_catalog_cache
from ..common.config import cfg
from ..common.signal_bus import signalBus


class CnCatalogLoadWorker(QThread):
    progress = Signal(str, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, data_dir: str, output_dir: str):
        super().__init__()
        self.data_dir = data_dir
        self.output_dir = output_dir

    def run(self):
        try:
            root = Path(self.data_dir)
            hotupdate = root if is_cn_hotupdate_dir(root) else find_cn_hotupdate_dir(root)
            if not hotupdate:
                self.error.emit("未找到国服 HotUpdate 目录（需含 assets_bundles_sound_songs_*）")
                return

            def on_progress(msg: str, pct: int) -> None:
                self.progress.emit(msg, pct)

            index = CnBundleIndex.scan(hotupdate, progress=on_progress)
            entries = scan_cn_catalog(root, Path(self.output_dir) if self.output_dir else None, index=index)
            self.finished.emit({"entries": entries, "index": index, "hotupdate": str(hotupdate)})
        except Exception as e:
            self.error.emit(str(e))


class CnExtractWorker(QThread):
    step = Signal(str, int)
    finished = Signal(str)
    error = Signal(str)
    log = Signal(str)

    def __init__(self, index: CnBundleIndex, music_id: int, output_dir: str):
        super().__init__()
        self.index = index
        self.music_id = music_id
        self.output_dir = output_dir

    def run(self):
        try:
            def on_progress(message: str, percent: int) -> None:
                self.step.emit(message, percent)
                self.log.emit(f"[{percent:3d}%] {message}")

            song_dir = extract_cn_song(
                self.index,
                self.music_id,
                Path(self.output_dir),
                progress=on_progress,
            )
            if song_dir:
                self.finished.emit(str(song_dir))
            else:
                self.error.emit("解包失败：未找到 BGM 或谱面资源")
        except Exception as e:
            self.error.emit(str(e))


class CnUnpackPage(ScrollArea):
    """国服曲库 + 单首解包"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cnUnpackPage")
        self._catalog_worker = None
        self._extract_worker = None
        self._entries: list[CnCatalogEntry] = []
        self._index: CnBundleIndex | None = None
        self._last_extracted_dir = ""
        self._setup_ui()
        self._connect_signals()
        QTimer.singleShot(100, self._try_restore_catalog)

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)

        path_card = CardWidget(container)
        path_layout = QVBoxLayout(path_card)
        path_layout.setContentsMargins(20, 16, 20, 16)
        path_layout.addWidget(BodyLabel("国服资源目录（HotUpdate 或安装根目录）"))
        game_row = QHBoxLayout()
        self.data_dir_edit = LineEdit(path_card)
        self.data_dir_edit.setPlaceholderText(
            r"例如 E:\Program Files (x86)\Jubeat CN\jubeat-file\jubeat-file\HotUpdate\JBT_Download\PC\100"
        )
        self.data_dir_edit.setClearButtonEnabled(True)
        if cfg.last_cn_dir:
            self.data_dir_edit.setText(cfg.last_cn_dir)
        self.data_browse_btn = PushButton(FIcon.FOLDER, "浏览", path_card)
        game_row.addWidget(self.data_dir_edit, 1)
        game_row.addWidget(self.data_browse_btn)
        path_layout.addLayout(game_row)

        path_layout.addWidget(BodyLabel("解包输出目录"))
        out_row = QHBoxLayout()
        self.output_dir_edit = LineEdit(path_card)
        self.output_dir_edit.setPlaceholderText("国服单曲解包保存位置...")
        self.output_dir_edit.setClearButtonEnabled(True)
        out_path = cfg.last_cn_output_dir or cfg.last_output_dir
        if out_path:
            self.output_dir_edit.setText(out_path)
        self.output_browse_btn = PushButton(FIcon.FOLDER, "浏览", path_card)
        out_row.addWidget(self.output_dir_edit, 1)
        out_row.addWidget(self.output_browse_btn)
        path_layout.addLayout(out_row)
        layout.addWidget(path_card)

        tool_card = CardWidget(container)
        tool_layout = QHBoxLayout(tool_card)
        tool_layout.setContentsMargins(20, 12, 20, 12)
        self.search_edit = LineEdit(tool_card)
        self.search_edit.setPlaceholderText("搜索曲名、艺术家或 ID...")
        self.search_edit.setClearButtonEnabled(True)
        self.diff_filter = ComboBox(tool_card)
        self.diff_filter.addItems(["全部", "BSC", "ADV", "EXT"])
        self.load_catalog_btn = PushButton(FIcon.SYNC, "刷新曲库", tool_card)
        self.extract_btn = PushButton(FIcon.DOWNLOAD, "提取选中曲", tool_card)
        self.extract_btn.setEnabled(False)
        self.convert_btn = PushButton(FIcon.SYNC, "转到 Malody 转换", tool_card)
        self.convert_btn.setEnabled(False)
        tool_layout.addWidget(BodyLabel("搜索:"))
        tool_layout.addWidget(self.search_edit, 1)
        tool_layout.addWidget(BodyLabel("难度:"))
        tool_layout.addWidget(self.diff_filter)
        tool_layout.addWidget(self.load_catalog_btn)
        tool_layout.addWidget(self.extract_btn)
        tool_layout.addWidget(self.convert_btn)
        layout.addWidget(tool_card)

        self.status_label = StrongBodyLabel("请选择国服目录和输出目录")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(
            ["曲名", "Music ID", "艺术家", "BPM", "BSC", "ADV", "EXT", "资源", "状态"]
        )
        self.table = TableView(container)
        self.table.setModel(self._model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(TableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table, 1)

        self.progress_bar = ProgressBar(container)
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.progress_label = BodyLabel("")
        self.progress_label.setStyleSheet("color: gray;")
        layout.addWidget(self.progress_label)

        log_card = CardWidget(container)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(20, 16, 20, 16)
        log_layout.addWidget(BodyLabel("提取日志"))
        self.log_edit = TextEdit(log_card)
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(140)
        log_layout.addWidget(self.log_edit)
        layout.addWidget(log_card)

        self.setWidget(container)

    def _connect_signals(self):
        self.data_browse_btn.clicked.connect(self._browse_data_dir)
        self.output_browse_btn.clicked.connect(self._browse_output_dir)
        self.load_catalog_btn.clicked.connect(lambda: self._load_catalog(force_refresh=True))
        self.output_dir_edit.textChanged.connect(self._on_output_dir_changed)
        self.extract_btn.clicked.connect(self._extract_selected)
        self.convert_btn.clicked.connect(self._go_convert)
        self.search_edit.textChanged.connect(self._filter_table)
        self.diff_filter.currentTextChanged.connect(lambda _: self._filter_table(self.search_edit.text()))
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def _browse_data_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择国服资源目录")
        if path:
            self.data_dir_edit.setText(path)
            cfg.last_cn_dir = path
            self._entries = []
            self._index = None
            self._try_restore_catalog()

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_dir_edit.setText(path)
            cfg.last_cn_output_dir = path
            self._on_output_dir_changed()

    def _paths_ready(self) -> bool:
        return bool(self.data_dir_edit.text().strip() and self.output_dir_edit.text().strip())

    def _on_output_dir_changed(self):
        if not self._entries:
            return
        output_dir = Path(self.output_dir_edit.text().strip())
        cfg.last_cn_output_dir = str(output_dir)
        refresh_cn_extracted_status(self._entries, output_dir)
        self._rebuild_table()

    def _try_restore_catalog(self):
        if not self._paths_ready():
            self.status_label.setText("请选择国服目录和输出目录")
            return
        if self._catalog_worker and self._catalog_worker.isRunning():
            return

        data_dir = Path(self.data_dir_edit.text().strip())
        output_dir = Path(self.output_dir_edit.text().strip())
        cached = load_cn_catalog_cache(data_dir, output_dir)
        if cached:
            entries, meta = cached
            self._apply_catalog(entries, meta, from_cache=True)
            return

        self.status_label.setText("未找到国服曲库缓存，请点击「刷新曲库」进行首次扫描")

    def _load_catalog(self, force_refresh: bool = False):
        if not self._paths_ready():
            InfoBar.warning("提示", "请先选择国服目录和输出目录", parent=self, position=InfoBarPosition.TOP)
            return
        if self._catalog_worker and self._catalog_worker.isRunning():
            return

        data_dir = self.data_dir_edit.text().strip()
        output_dir = self.output_dir_edit.text().strip()
        cfg.last_cn_dir = data_dir
        cfg.last_cn_output_dir = output_dir

        self._catalog_worker = CnCatalogLoadWorker(data_dir, output_dir)
        self._catalog_worker.progress.connect(self._on_catalog_progress)
        self._catalog_worker.finished.connect(self._on_catalog_loaded)
        self._catalog_worker.error.connect(self._on_catalog_error)
        self.load_catalog_btn.setDisabled(True)
        self.extract_btn.setDisabled(True)
        self.status_label.setText("正在加载国服曲库...")
        self.progress_bar.setValue(0)
        self._catalog_worker.start()

    @Slot(str, int)
    def _on_catalog_progress(self, msg: str, pct: int):
        self.status_label.setText(msg)
        self.progress_bar.setValue(pct)
        self._append_log(msg)

    def _on_catalog_loaded(self, payload: dict):
        entries = payload["entries"]
        self._index = payload["index"]
        save_cn_catalog_cache(Path(self.data_dir_edit.text().strip()), entries)
        self._apply_catalog(entries, {"from_cache": False}, from_cache=False)

    def _apply_catalog(self, entries: list, meta: dict, *, from_cache: bool):
        self._entries = entries
        self._rebuild_table()
        self.load_catalog_btn.setEnabled(True)
        self.extract_btn.setEnabled(bool(self.table.selectionModel().selectedRows()))
        source = "缓存" if from_cache else "扫描"
        cached_at = meta.get("cached_at", "")
        if from_cache and cached_at:
            self.status_label.setText(f"国服曲库已从缓存恢复：共 {len(entries)} 首（{cached_at[:19]}）")
        else:
            self.status_label.setText(f"国服曲库已{source}加载：共 {len(entries)} 首")
        self.progress_bar.setValue(100)
        self.progress_label.setText("")

    def _rebuild_table(self):
        self._model.removeRows(0, self._model.rowCount())
        for entry in self._entries:
            self._append_entry_row(entry)
        self._filter_table()

    def _append_entry_row(self, entry: CnCatalogEntry):
        res_parts = []
        if entry.has_bgm:
            res_parts.append("音")
        if entry.has_chart:
            res_parts.append("谱")
        if entry.has_jacket:
            res_parts.append("图")

        name_item = QStandardItem(entry.title)
        name_item.setData(entry.music_id, Qt.ItemDataRole.UserRole)
        if entry.extracted_dir:
            name_item.setData(str(entry.extracted_dir), Qt.ItemDataRole.UserRole + 1)

        row = [
            name_item,
            QStandardItem(str(entry.music_id)),
            QStandardItem(entry.artist),
            QStandardItem(entry.bpm),
            QStandardItem(entry.levels.get("bsc") or entry.levels.get("BSC", "-")),
            QStandardItem(entry.levels.get("adv") or entry.levels.get("ADV", "-")),
            QStandardItem(entry.levels.get("ext") or entry.levels.get("EXT", "-")),
            QStandardItem("/".join(res_parts) or "—"),
            QStandardItem(entry.status),
        ]
        for item in row:
            item.setEditable(False)
        self._model.appendRow(row)

    def _filter_table(self, text: str = ""):
        text = (text or self.search_edit.text()).strip().lower()
        diff = self.diff_filter.currentText()
        diff_col = {"BSC": 4, "ADV": 5, "EXT": 6}.get(diff)

        for row in range(self._model.rowCount()):
            visible = True
            if text:
                cells = [
                    self._model.item(row, col).text().lower()
                    for col in range(self._model.columnCount())
                    if self._model.item(row, col)
                ]
                visible = any(text in cell for cell in cells)
            if visible and diff_col is not None:
                level_item = self._model.item(row, diff_col)
                if level_item and level_item.text().strip() in ("", "-"):
                    visible = False
            self.table.setRowHidden(row, not visible)

    def _on_selection_changed(self):
        has_sel = bool(self.table.selectionModel().selectedRows())
        busy = self._extract_worker is not None and self._extract_worker.isRunning()
        entry = self._selected_entry() if has_sel else None
        can_extract = has_sel and not busy and entry is not None and entry.has_bgm
        self.extract_btn.setEnabled(can_extract)

    def _selected_entry(self) -> CnCatalogEntry | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        music_id = self._model.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for entry in self._entries:
            if entry.music_id == music_id:
                return entry
        return None

    def _ensure_index(self) -> bool:
        if self._index is not None:
            return True
        root = Path(self.data_dir_edit.text().strip())
        hotupdate = root if is_cn_hotupdate_dir(root) else find_cn_hotupdate_dir(root)
        if not hotupdate:
            InfoBar.warning("提示", "无法定位国服 HotUpdate 目录，请刷新曲库", parent=self, position=InfoBarPosition.TOP)
            return False
        self._index = CnBundleIndex.scan(hotupdate, load_song_list=False)
        return True

    def _extract_selected(self):
        entry = self._selected_entry()
        if not entry:
            return
        if not self._ensure_index():
            return
        if self._extract_worker and self._extract_worker.isRunning():
            return

        output_dir = self.output_dir_edit.text().strip()
        self.log_edit.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"正在提取: {entry.title}")
        self.extract_btn.setDisabled(True)
        self.load_catalog_btn.setDisabled(True)

        self._extract_worker = CnExtractWorker(self._index, entry.music_id, output_dir)
        self._extract_worker.step.connect(self._on_extract_step)
        self._extract_worker.log.connect(self._append_log)
        self._extract_worker.finished.connect(self._on_extract_finished)
        self._extract_worker.error.connect(self._on_extract_error)
        self._extract_worker.start()

    @Slot(str, int)
    def _on_extract_step(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def _on_extract_finished(self, song_dir: str):
        self._last_extracted_dir = song_dir
        self.load_catalog_btn.setEnabled(True)
        self.extract_btn.setEnabled(True)
        self.convert_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.progress_label.setText("提取完成")
        self.status_label.setText(f"已提取: {Path(song_dir).name}")

        entry = self._selected_entry()
        if entry:
            entry.extracted_dir = Path(song_dir)
            rows = self.table.selectionModel().selectedRows()
            if rows:
                row = rows[0].row()
                self._model.item(row, 8).setText("已提取")
                self._model.item(row, 0).setData(song_dir, Qt.ItemDataRole.UserRole + 1)
            save_cn_catalog_cache(Path(self.data_dir_edit.text().strip()), self._entries)

        signalBus.song_extracted.emit(song_dir)
        signalBus.unpack_finished.emit(str(Path(song_dir).parent))
        InfoBar.success("提取完成", f"已保存到 {song_dir}", parent=self, position=InfoBarPosition.TOP, duration=4000)

    def _on_catalog_error(self, msg: str):
        self.load_catalog_btn.setEnabled(True)
        self.status_label.setText(f"加载失败: {msg}")
        InfoBar.error("曲库加载失败", msg, parent=self, position=InfoBarPosition.TOP)

    def _on_extract_error(self, msg: str):
        self.load_catalog_btn.setEnabled(True)
        self.extract_btn.setEnabled(True)
        self.progress_label.setText(f"失败: {msg}")
        self._append_log(f"错误: {msg}")
        InfoBar.error("提取失败", msg, parent=self, position=InfoBarPosition.TOP)

    def _go_convert(self):
        song_dir = self._last_extracted_dir
        rows = self.table.selectionModel().selectedRows()
        if rows:
            stored = self._model.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole + 1)
            if stored:
                song_dir = stored
        if not song_dir:
            InfoBar.warning("提示", "请先提取一首乐曲", parent=self, position=InfoBarPosition.TOP)
            return
        signalBus.song_selected.emit(song_dir)
        signalBus.open_convert_page.emit()

    @Slot(str)
    def _append_log(self, msg: str):
        self.log_edit.append(msg)
        bar = self.log_edit.verticalScrollBar()
        bar.setValue(bar.maximum())
