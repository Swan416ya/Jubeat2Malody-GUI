"""
全局配置

参考 QFluentWidgets demo 的 cfg 模式，使用 QSettings 持久化用户偏好。
"""

from PySide6.QtCore import QSettings


class Config:
    """应用配置，基于 QSettings 自动持久化"""

    def __init__(self):
        self._settings = QSettings("Jubeat2Malody", "Jubeat2Malody")

    # --- 路径 ---
    @property
    def last_ifs_dir(self) -> str:
        return self._settings.value("paths/last_ifs_dir", "")

    @last_ifs_dir.setter
    def last_ifs_dir(self, val: str):
        self._settings.setValue("paths/last_ifs_dir", val)

    @property
    def last_output_dir(self) -> str:
        return self._settings.value("paths/last_output_dir", "")

    @last_output_dir.setter
    def last_output_dir(self, val: str):
        self._settings.setValue("paths/last_output_dir", val)

    @property
    def last_cn_dir(self) -> str:
        return self._settings.value("paths/last_cn_dir", "")

    @last_cn_dir.setter
    def last_cn_dir(self, val: str):
        self._settings.setValue("paths/last_cn_dir", val)

    @property
    def last_cn_output_dir(self) -> str:
        return self._settings.value("paths/last_cn_output_dir", "")

    @last_cn_output_dir.setter
    def last_cn_output_dir(self, val: str):
        self._settings.setValue("paths/last_cn_output_dir", val)

    @property
    def last_convert_dir(self) -> str:
        return self._settings.value("paths/last_convert_dir", "")

    @last_convert_dir.setter
    def last_convert_dir(self, val: str):
        self._settings.setValue("paths/last_convert_dir", val)

    # --- 转换选项 ---
    @property
    def skip_existing(self) -> bool:
        return self._settings.value("convert/skip_existing", True, type=bool)

    @skip_existing.setter
    def skip_existing(self, val: bool):
        self._settings.setValue("convert/skip_existing", val)

    @property
    def audio_format(self) -> str:
        return self._settings.value("convert/audio_format", "ogg")

    @audio_format.setter
    def audio_format(self, val: str):
        self._settings.setValue("convert/audio_format", val)

    # --- 预览选项 ---
    @property
    def preview_speed(self) -> float:
        return self._settings.value("preview/speed", 1.0, type=float)

    @preview_speed.setter
    def preview_speed(self, val: float):
        self._settings.setValue("preview/speed", val)


cfg = Config()
