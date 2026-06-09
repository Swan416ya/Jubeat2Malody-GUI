"""
Jubeat2Malody GUI 主入口

启动 FluentWindow 主窗口，注册曲库/预览/转换三个子页面。
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentWindow, FluentIcon as FIcon, setTheme, Theme

from .pages.unpack_page import UnpackPage
from .pages.preview_page import PreviewPage
from .pages.convert_page import ConvertPage
from .common.signal_bus import signalBus
from .common.config import cfg


class MainWindow(FluentWindow):
    """主窗口 — 侧边导航 + 四个子页面"""

    def __init__(self):
        super().__init__()
        self._init_pages()
        self._init_navigation()
        self._connect_signals()
        self._init_window()

    def _init_pages(self):
        self.unpack_page = UnpackPage(self)
        self.preview_page = PreviewPage(self)
        self.convert_page = ConvertPage(self)
    def _init_navigation(self):
        self.addSubInterface(self.unpack_page, FIcon.LIBRARY, "曲库")
        self.addSubInterface(self.preview_page, FIcon.PLAY, "预览")
        self.addSubInterface(self.convert_page, FIcon.SYNC, "转换")

    def _connect_signals(self):
        signalBus.chart_loaded.connect(self._open_preview)
        signalBus.open_convert_page.connect(self._open_convert)

    def _open_preview(self, _data: dict):
        self.switchTo(self.preview_page)

    def _open_convert(self):
        self.switchTo(self.convert_page)

    def _init_window(self):
        self.resize(1100, 750)
        self.setMinimumWidth(900)
        self.setMinimumHeight(600)
        self.setWindowIcon(QIcon())
        self.setWindowTitle("Jubeat2Malody")
        self.navigationInterface.setExpandWidth(200)

        # 居中显示
        desktop = QApplication.screens()[0].availableGeometry()
        self.move(
            (desktop.width() - self.width()) // 2,
            (desktop.height() - self.height()) // 2,
        )

        setTheme(Theme.AUTO)


def main():
    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Jubeat2Malody")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
