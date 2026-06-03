"""
转换页面 — 选择一首歌的文件夹，将 EVE 谱面 + 音频转为 Malody .mcz

文件夹结构预期:
  song_folder/
    ├── bgm.wav (或 bgm.ogg / bgm.bin)
    ├── bsc.eve
    ├── adv.eve
    └── ext.eve
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    ScrollArea, PushButton, LineEdit,
    TextEdit, FluentIcon as FIcon, CardWidget, BodyLabel,
    CheckBox, InfoBar, InfoBarPosition, StrongBodyLabel,
)

from ...core.malody_writer import convert_single_song
from ..common.signal_bus import signalBus
from ..common.config import cfg


class ConvertWorker(QThread):
    """后台转换单首歌曲"""
    finished = Signal(str)      # 输出 .mcz 路径
    error = Signal(str)         # 错误信息
    log = Signal(str)           # 日志消息

    def __init__(self, song_dir: str, output_dir: str, skip_existing: bool):
        super().__init__()
        self.song_dir = song_dir
        self.output_dir = output_dir
        self.skip_existing = skip_existing

    def run(self):
        try:
            result = convert_single_song(
                Path(self.song_dir), Path(self.output_dir), self.skip_existing
            )
            if result:
                self.log.emit(f"转换成功: {result.name}")
                self.finished.emit(str(result))
            else:
                self.error.emit("转换失败：未找到有效的谱面文件或音频文件")
        except Exception as e:
            self.error.emit(str(e))


class ConvertPage(ScrollArea):
    """转换页面 — 选择歌曲文件夹，转换单首歌曲为 Malody .mcz"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("convertPage")
        self._worker = None
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        c = QWidget()
        lo = QVBoxLayout(c)
        lo.setContentsMargins(36, 20, 36, 20)
        lo.setSpacing(16)

        # --- 歌曲文件夹选择 ---
        src_card = CardWidget(c)
        sl = QVBoxLayout(src_card)
        sl.setContentsMargins(20, 16, 20, 16)
        sl.addWidget(BodyLabel("歌曲文件夹 (含音频 + .eve 谱面)"))
        sr = QHBoxLayout()
        self.src_edit = LineEdit(src_card)
        self.src_edit.setPlaceholderText("选择包含 bgm.wav 和 bsc.eve/adv.eve/ext.eve 的文件夹...")
        self.src_edit.setClearButtonEnabled(True)
        self.src_btn = PushButton(FIcon.FOLDER, "浏览", src_card)
        sr.addWidget(self.src_edit, 1)
        sr.addWidget(self.src_btn)
        sl.addLayout(sr)

        # 文件夹内容预览
        self.preview_label = StrongBodyLabel("")
        self.preview_label.setStyleSheet("color: gray; font-size: 12px;")
        sl.addWidget(self.preview_label)
        lo.addWidget(src_card)

        # --- 输出目录 ---
        out_card = CardWidget(c)
        ol = QVBoxLayout(out_card)
        ol.setContentsMargins(20, 16, 20, 16)
        ol.addWidget(BodyLabel("输出目录 (.mcz 保存位置)"))
        orr = QHBoxLayout()
        self.out_edit = LineEdit(out_card)
        self.out_edit.setPlaceholderText("选择 .mcz 保存位置...")
        self.out_edit.setClearButtonEnabled(True)
        if cfg.last_convert_dir:
            self.out_edit.setText(cfg.last_convert_dir)
        self.out_btn = PushButton(FIcon.FOLDER, "浏览", out_card)
        orr.addWidget(self.out_edit, 1)
        orr.addWidget(self.out_btn)
        ol.addLayout(orr)
        lo.addWidget(out_card)

        # --- 选项 ---
        opt_card = CardWidget(c)
        opl = QHBoxLayout(opt_card)
        opl.setContentsMargins(20, 16, 20, 16)
        self.skip_cb = CheckBox("跳过已存在的文件", opt_card)
        self.skip_cb.setChecked(cfg.skip_existing)
        opl.addWidget(self.skip_cb)
        opl.addStretch(1)
        lo.addWidget(opt_card)

        # --- 按钮 ---
        br = QHBoxLayout()
        self.convert_btn = PushButton(FIcon.SYNC, "转换", c)
        self.convert_btn.setDisabled(True)
        self.stop_btn = PushButton(FIcon.CANCEL, "停止", c)
        self.stop_btn.setDisabled(True)
        br.addWidget(self.convert_btn)
        br.addWidget(self.stop_btn)
        br.addStretch(1)
        lo.addLayout(br)

        # --- 日志 ---
        self.log_edit = TextEdit(c)
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("转换日志将在此显示...")
        self.log_edit.setMinimumHeight(180)
        lo.addWidget(self.log_edit, 1)

        lo.addStretch(1)
        self.setWidget(c)

    def _connect_signals(self):
        self.src_btn.clicked.connect(self._browse_src)
        self.out_btn.clicked.connect(self._browse_out)
        self.convert_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)
        self.src_edit.textChanged.connect(self._update_btn)
        self.out_edit.textChanged.connect(self._update_btn)
        signalBus.song_selected.connect(self._on_song_selected)

    def _browse_src(self):
        p = QFileDialog.getExistingDirectory(self, "选择歌曲文件夹")
        if p:
            self.src_edit.setText(p)
            self._preview_folder(p)

    def _browse_out(self):
        p = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if p:
            self.out_edit.setText(p)
            cfg.last_convert_dir = p

    def _preview_folder(self, path: str):
        """预览文件夹内容，显示找到的文件"""
        d = Path(path)
        if not d.is_dir():
            self.preview_label.setText("")
            return

        audio = [f.name for f in d.iterdir() if f.suffix.lower() in (".wav", ".ogg", ".bin") and "bgm" in f.name.lower()]
        eves = [f.name for f in d.iterdir() if f.suffix.lower() == ".eve"]
        info = [f.name for f in d.iterdir() if f.name == "song_info.txt"]
        imgs = [f.name for f in d.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")]

        parts = []
        if audio:
            parts.append(f"音频: {', '.join(audio)}")
        if eves:
            parts.append(f"谱面: {', '.join(eves)}")
        if imgs:
            parts.append(f"封面: {', '.join(imgs)}")
        if info:
            parts.append("元数据: song_info.txt")

        if parts:
            self.preview_label.setStyleSheet("color: #10b981; font-size: 12px;")
            self.preview_label.setText("  |  ".join(parts))
        else:
            self.preview_label.setStyleSheet("color: #ef4444; font-size: 12px;")
            self.preview_label.setText("未找到有效的音频或谱面文件")

    def _on_song_selected(self, song_dir: str):
        """从管理页双击选中歌曲时自动填充"""
        self.src_edit.setText(song_dir)
        self._preview_folder(song_dir)

    def _update_btn(self):
        ready = bool(self.src_edit.text().strip() and self.out_edit.text().strip())
        self.convert_btn.setEnabled(ready and self._worker is None)
        # 路径变化时更新预览
        src = self.src_edit.text().strip()
        if src and Path(src).is_dir():
            self._preview_folder(src)

    def _start(self):
        song_dir = self.src_edit.text().strip()
        output_dir = self.out_edit.text().strip()

        if not Path(song_dir).is_dir():
            InfoBar.warning("提示", "歌曲文件夹不存在", parent=self, position=InfoBarPosition.TOP)
            return

        self._worker = ConvertWorker(song_dir, output_dir, self.skip_cb.isChecked())
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.log.connect(self.log_edit.append)

        self.convert_btn.setDisabled(True)
        self.stop_btn.setEnabled(True)
        self.log_edit.clear()
        signalBus.convert_started.emit(output_dir)
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(3000)
        self._on_done("")

    def _on_done(self, out: str):
        self._worker = None
        self.convert_btn.setEnabled(True)
        self.stop_btn.setDisabled(True)
        if out:
            signalBus.convert_finished.emit(out)
            InfoBar.success("转换完成", f"已保存到: {out}", parent=self, position=InfoBarPosition.TOP, duration=3000)

    def _on_error(self, msg: str):
        self._worker = None
        self.convert_btn.setEnabled(True)
        self.stop_btn.setDisabled(True)
        InfoBar.error("转换失败", msg, parent=self, position=InfoBarPosition.TOP, duration=5000)
