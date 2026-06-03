"""
全局信号总线

参考 QFluentWidgets demo 的 signalBus 模式，用于跨组件通信。
所有信号定义在此，各页面/组件通过 connect 建立联系。
"""

from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    """全局信号总线"""

    # --- 解包相关 ---
    # str: 解包输出目录路径
    unpack_started = Signal(str)
    unpack_finished = Signal(str)       # 输出目录
    unpack_error = Signal(str)          # 错误信息

    # --- 转换相关 ---
    # str: 转换输出目录路径
    convert_started = Signal(str)
    convert_finished = Signal(str)      # 输出 .mcz 路径
    convert_error = Signal(str)         # 错误信息

    # --- 预览相关 ---
    # dict: 谱面数据
    chart_loaded = Signal(dict)
    preview_play = Signal()
    preview_pause = Signal()
    preview_stop = Signal()

    # --- 管理相关 ---
    song_selected = Signal(str)         # 歌曲目录路径
    song_list_refreshed = Signal()


signalBus = SignalBus()
