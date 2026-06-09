"""谱面预览用音频播放器（Qt Multimedia）。"""

from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class ChartAudioPlayer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._loaded_path: Path | None = None

    def load(self, path: Path) -> bool:
        if not path.is_file():
            return False
        self._loaded_path = path
        self._player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        return True

    def play(self, position_ms: int = 0) -> None:
        if position_ms > 0:
            self._player.setPosition(position_ms)
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()
        self._player.setPosition(0)

    def set_position_ms(self, position_ms: int) -> None:
        self._player.setPosition(max(0, position_ms))

    def position_ms(self) -> int:
        return self._player.position()

    def duration_ms(self) -> int:
        return self._player.duration()

    def is_loaded(self) -> bool:
        return self._loaded_path is not None

    def set_playback_rate(self, rate: float) -> None:
        self._audio.setVolume(1.0)
        self._player.setPlaybackRate(max(0.25, min(3.0, rate)))
