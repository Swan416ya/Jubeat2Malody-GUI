"""
转换页面 — EVE → Malody .mc/.mcz 批量/单文件转换
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    ScrollArea, PushButton, LineEdit, ProgressBar,
    TextEdit, FluentIcon as FIcon, CardWidget, BodyLabel,
    CheckBox, InfoBar, InfoBarPosition,
)

from ...core.malody_writer import convert_song
from ..common.signal_bus import signalBus
from ..common.config import cfg


class ConvertWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(str)
    error = Signal(str)
    log = Signal(str)

    def __init__(self, song_dirs: list, output_dir: str, skip_existing: bool):
        super().__init__()
        self.song_dirs = song_dirs
        self.output_dir = output_dir
        self.skip_existing = skip_existing

    def run(self):
        out = Path(self.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ok = 0
        for i, d in enumerate(self.song_dirs):
            self.progress.emit(i + 1, len(self.song_dirs))
            try:
                r = convert_song(Path(d), out, self.skip_existing)
                if r:
                    self.log.emit(f"转换成功: {r.name}")
                    ok += 1
                else:
                    self.log.emit(f"跳过(无谱面): {Path(d).name}")
            except Exception as e:
                self.log.emit(f"出错: {Path(d).name} — {e}")
        self.log.emit(f"完成! 成功 {ok}/{len(self.song_dirs)}")
        self.finished.emit(self.output_dir)


class ConvertPage(ScrollArea):
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

        # 源目录
        sc = CardWidget(c)
        sl = QVBoxLayout(sc); sl.setContentsMargins(20, 16, 20, 16)
        sl.addWidget(BodyLabel("已解包歌曲目录"))
        sr = QHBoxLayout()
        self.src_edit = LineEdit(sc)
        self.src_edit.setPlaceholderText("选择包含 song_info.txt 的解包目录...")
        if cfg.last_output_dir:
            self.src_edit.setText(cfg.last_output_dir)
        self.src_btn = PushButton(FIcon.FOLDER, "浏览", sc)
        sr.addWidget(self.src_edit, 1); sr.addWidget(self.src_btn)
        sl.addLayout(sr)
        lo.addWidget(sc)

        # 输出目录
        oc = CardWidget(c)
        ol = QVBoxLayout(oc); ol.setContentsMargins(20, 16, 20, 16)
        ol.addWidget(BodyLabel("Malody 谱面包输出目录"))
        orr = QHBoxLayout()
        self.out_edit = LineEdit(oc)
        self.out_edit.setPlaceholderText("选择 .mcz 保存位置...")
        if cfg.last_convert_dir:
            self.out_edit.setText(cfg.last_convert_dir)
        self.out_btn = PushButton(FIcon.FOLDER, "浏览", oc)
        orr.addWidget(self.out_edit, 1); orr.addWidget(self.out_btn)
        ol.addLayout(orr)
        lo.addWidget(oc)

        # 选项
        opc = CardWidget(c)
        opl = QHBoxLayout(opc); opl.setContentsMargins(20, 16, 20, 16)
        self.skip_cb = CheckBox("跳过已存在的文件", opc)
        self.skip_cb.setChecked(cfg.skip_existing)
        opl.addWidget(self.skip_cb); opl.addStretch(1)
        lo.addWidget(opc)

        # 按钮
        br = QHBoxLayout()
        self.convert_btn = PushButton(FIcon.SYNC, "开始转换", c)
        self.convert_btn.setDisabled(True)
        self.stop_btn = PushButton(FIcon.CANCEL, "停止", c)
        self.stop_btn.setDisabled(True)
        br.addWidget(self.convert_btn); br.addWidget(self.stop_btn); br.addStretch(1)
        lo.addLayout(br)

        self.progress_bar = ProgressBar(c)
        lo.addWidget(self.progress_bar)

        self.log_edit = TextEdit(c)
        self.log_edit.setReadOnly(True)
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
        signalBus.unpack_finished.connect(self.src_edit.setText)

    def _browse_src(self):
        p = QFileDialog.getExistingDirectory(self, "选择解包目录")
        if p: self.src_edit.setText(p)

    def _browse_out(self):
        p = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if p: self.out_edit.setText(p); cfg.last_convert_dir = p

    def _update_btn(self):
        r = bool(self.src_edit.text().strip() and self.out_edit.text().strip())
        self.convert_btn.setEnabled(r and self._worker is None)

    def _start(self):
        src = Path(self.src_edit.text().strip())
        dirs = [str(d) for d in src.iterdir() if d.is_dir() and (d / "song_info.txt").exists()]
        if not dirs:
            InfoBar.warning("提示", "未找到有效的歌曲目录", parent=self, position=InfoBarPosition.TOP)
            return
        self._worker = ConvertWorker(dirs, self.out_edit.text().strip(), self.skip_cb.isChecked())
        self._worker.progress.connect(lambda c, t: self.progress_bar.setValue(int(c / t * 100)))
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(lambda m: InfoBar.error("转换失败", m, parent=self, position=InfoBarPosition.TOP))
        self._worker.log.connect(self.log_edit.append)
        self.convert_btn.setDisabled(True); self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0); self.log_edit.clear()
        signalBus.convert_started.emit(self.out_edit.text())
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate(); self._worker.wait(3000)
        self._on_done("")

    def _on_done(self, out: str):
        self._worker = None
        self.convert_btn.setEnabled(True); self.stop_btn.setDisabled(True)
        if out:
            signalBus.convert_finished.emit(out)
            InfoBar.success("转换完成", f"已保存到: {out}", parent=self, position=InfoBarPosition.TOP, duration=3000)
