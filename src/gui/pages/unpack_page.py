"""
解包页面

从 Jubeat 游戏目录中选择 IFS 文件并批量解包，
提取谱面 (EVE)、音频 (BGM) 和元数据。
"""

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QFileDialog,
)
from qfluentwidgets import (
    ScrollArea, PushButton, LineEdit, ProgressBar,
    TextEdit, FluentIcon as FIcon, CardWidget, BodyLabel,
    InfoBar, InfoBarPosition,
)

from ...core.unpacker import extract_song, load_music_info, is_ifs_encrypted, load_word_info
from ..common.signal_bus import signalBus
from ..common.config import cfg


class UnpackWorker(QThread):
    """后台解包线程"""
    progress = Signal(int, int)        # current, total
    finished = Signal(str)             # output_dir
    error = Signal(str)                # error_msg
    log = Signal(str)                  # log message

    def __init__(self, ifs_dir: str, output_dir: str):
        super().__init__()
        self.ifs_dir = ifs_dir
        self.output_dir = output_dir

    def run(self):
        from pathlib import Path

        ifs_path = Path(self.ifs_dir)
        output_path = Path(self.output_dir)

        # 查找 music_info.xml
        music_info_path = ifs_path / "music_info.xml"
        music_info = {}
        if music_info_path.exists():
            music_info = load_music_info(music_info_path)
            self.log.emit(f"已加载歌曲元数据: {len(music_info)} 首")

        # 查找 word_info.xml (可能包含更完整的曲名)
        word_info_path = ifs_path / "word_info.xml"
        word_info = {}
        if word_info_path.exists():
            word_info = load_word_info(word_info_path)
            if word_info:
                self.log.emit(f"已加载文本信息: {len(word_info)} 首")

        # 查找所有 IFS 文件
        ifs_files = sorted(ifs_path.rglob("*_msc.ifs"))
        if not ifs_files:
            self.error.emit("未找到任何 IFS 文件 (*_msc.ifs)")
            return

        self.log.emit(f"找到 {len(ifs_files)} 个 IFS 文件")

        success_count = 0
        for i, ifs_file in enumerate(ifs_files):
            self.progress.emit(i + 1, len(ifs_files))

            if is_ifs_encrypted(ifs_file):
                self.log.emit(f"跳过(加密): {ifs_file.name}")
                continue

            try:
                song_dir = extract_song(ifs_file, music_info, output_path, ifs_dir=ifs_path)
                if song_dir:
                    self.log.emit(f"解包成功: {song_dir.name}")
                    success_count += 1
                else:
                    self.log.emit(f"解包失败(空): {ifs_file.name}")
            except Exception as e:
                self.log.emit(f"解包出错: {ifs_file.name} — {e}")

        self.log.emit(f"完成! 成功 {success_count}/{len(ifs_files)}")
        self.finished.emit(self.output_dir)


class UnpackPage(ScrollArea):
    """解包页面 — 选择目录、批量解包 IFS"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("unpackPage")
        self._worker = None

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        self.vBoxLayout = QVBoxLayout(container)
        self.vBoxLayout.setContentsMargins(36, 20, 36, 20)
        self.vBoxLayout.setSpacing(16)

        # --- IFS 目录选择 ---
        self.ifs_card = CardWidget(container)
        ifs_layout = QVBoxLayout(self.ifs_card)
        ifs_layout.setContentsMargins(20, 16, 20, 16)

        ifs_layout.addWidget(BodyLabel("游戏数据目录 (含 IFS 文件)"))
        ifs_dir_row = QHBoxLayout()
        self.ifs_dir_edit = LineEdit(self.ifs_card)
        self.ifs_dir_edit.setPlaceholderText("选择包含 ifs_pack/ 的游戏数据目录...")
        self.ifs_dir_edit.setClearButtonEnabled(True)
        if cfg.last_ifs_dir:
            self.ifs_dir_edit.setText(cfg.last_ifs_dir)
        self.ifs_browse_btn = PushButton(FIcon.FOLDER, "浏览", self.ifs_card)
        ifs_dir_row.addWidget(self.ifs_dir_edit, 1)
        ifs_dir_row.addWidget(self.ifs_browse_btn)
        ifs_layout.addLayout(ifs_dir_row)
        self.vBoxLayout.addWidget(self.ifs_card)

        # --- 输出目录选择 ---
        self.output_card = CardWidget(container)
        output_layout = QVBoxLayout(self.output_card)
        output_layout.setContentsMargins(20, 16, 20, 16)

        output_layout.addWidget(BodyLabel("解包输出目录"))
        output_dir_row = QHBoxLayout()
        self.output_dir_edit = LineEdit(self.output_card)
        self.output_dir_edit.setPlaceholderText("选择解包后文件的保存位置...")
        self.output_dir_edit.setClearButtonEnabled(True)
        if cfg.last_output_dir:
            self.output_dir_edit.setText(cfg.last_output_dir)
        self.output_browse_btn = PushButton(FIcon.FOLDER, "浏览", self.output_card)
        output_dir_row.addWidget(self.output_dir_edit, 1)
        output_dir_row.addWidget(self.output_browse_btn)
        output_layout.addLayout(output_dir_row)
        self.vBoxLayout.addWidget(self.output_card)

        # --- 操作按钮 ---
        btn_row = QHBoxLayout()
        self.unpack_btn = PushButton(FIcon.ZIP_FOLDER, "开始解包", container)
        self.unpack_btn.setDisabled(True)
        self.stop_btn = PushButton(FIcon.CANCEL, "停止", container)
        self.stop_btn.setDisabled(True)
        btn_row.addWidget(self.unpack_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch(1)
        self.vBoxLayout.addLayout(btn_row)

        # --- 进度条 ---
        self.progress_bar = ProgressBar(container)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.vBoxLayout.addWidget(self.progress_bar)

        # --- 日志 ---
        self.log_edit = TextEdit(container)
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("解包日志将在此显示...")
        self.log_edit.setMinimumHeight(200)
        self.vBoxLayout.addWidget(self.log_edit, 1)

        self.vBoxLayout.addStretch(1)
        self.setWidget(container)

    def _connect_signals(self):
        self.ifs_browse_btn.clicked.connect(self._browse_ifs_dir)
        self.output_browse_btn.clicked.connect(self._browse_output_dir)
        self.unpack_btn.clicked.connect(self._start_unpack)
        self.stop_btn.clicked.connect(self._stop_unpack)

        # 输入变化时启用/禁用按钮
        self.ifs_dir_edit.textChanged.connect(self._update_btn_state)
        self.output_dir_edit.textChanged.connect(self._update_btn_state)

        # 初始化按钮状态（config 预填充的文本在信号连接前已设置，需手动触发一次）
        self._update_btn_state()

    def _browse_ifs_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择游戏数据目录")
        if path:
            self.ifs_dir_edit.setText(path)
            cfg.last_ifs_dir = path

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_dir_edit.setText(path)
            cfg.last_output_dir = path

    def _update_btn_state(self):
        ready = bool(self.ifs_dir_edit.text().strip() and self.output_dir_edit.text().strip())
        self.unpack_btn.setEnabled(ready and self._worker is None)

    def _start_unpack(self):
        ifs_dir = self.ifs_dir_edit.text().strip()
        output_dir = self.output_dir_edit.text().strip()

        self._worker = UnpackWorker(ifs_dir, output_dir)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.log.connect(self._on_log)

        self.unpack_btn.setDisabled(True)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_edit.clear()

        signalBus.unpack_started.emit(output_dir)
        self._worker.start()

    def _stop_unpack(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(3000)
            self._on_log("用户已停止解包")
            self._on_finished("")

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setValue(int(current / total * 100))

    def _on_finished(self, output_dir: str):
        self._worker = None
        self.unpack_btn.setEnabled(True)
        self.stop_btn.setDisabled(True)
        if output_dir:
            signalBus.unpack_finished.emit(output_dir)
            InfoBar.success(
                "解包完成", f"文件已保存到: {output_dir}",
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )

    def _on_error(self, msg: str):
        self._worker = None
        self.unpack_btn.setEnabled(True)
        self.stop_btn.setDisabled(True)
        signalBus.unpack_error.emit(msg)
        InfoBar.error(
            "解包失败", msg,
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )

    def _on_log(self, msg: str):
        self.log_edit.append(msg)
