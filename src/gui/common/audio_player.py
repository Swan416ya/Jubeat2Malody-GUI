"""谱面预览用音频播放器（Qt Multimedia）。"""

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class ChartAudioPlayer(QObject):
    """等待媒体加载完成后再播放，供谱面预览与 BGM 同步。"""

    media_ready = Signal()
    media_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._loaded_path: Path | None = None
        self._ready = False
        self._pending_play = False
        self._pending_position_ms = 0
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

    def load(self, path: Path) -> bool:
        if not path.is_file():
            self._loaded_path = None
            self._ready = False
            return False
        self._ready = False
        self._pending_play = False
        self._pending_position_ms = 0
        self._loaded_path = path
        self._player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        return True

    def play(self, position_ms: int = 0) -> None:
        if not self.is_loaded():
            return
        if not self._ready or self.duration_ms() <= 0:
            self._pending_play = True
            self._pending_position_ms = max(0, position_ms)
            return
        self._do_play(position_ms)

    def _do_play(self, position_ms: int = 0) -> None:
        if position_ms > 0:
            self._player.setPosition(position_ms)
        self._player.play()

    def pause(self) -> None:
        self._pending_play = False
        self._player.pause()

    def stop(self) -> None:
        self._pending_play = False
        self._pending_position_ms = 0
        self._player.stop()
        self._player.setPosition(0)

    def set_position_ms(self, position_ms: int) -> None:
        self._player.setPosition(max(0, position_ms))

    def position_ms(self) -> int:
        return self._player.position()

    def duration_ms(self) -> int:
        duration = self._player.duration()
        return duration if duration > 0 else 0

    def is_loaded(self) -> bool:
        return self._loaded_path is not None

    @property
    def loaded_path(self) -> Path | None:
        return self._loaded_path

    def is_ready(self) -> bool:
        return self._ready and self.duration_ms() > 0

    def set_playback_rate(self, rate: float) -> None:
        self._audio.setVolume(1.0)
        self._player.setPlaybackRate(max(0.25, min(3.0, rate)))

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            if self.duration_ms() > 0:
                self._ready = True
                self.media_ready.emit()
                if self._pending_play:
                    self._pending_play = False
                    self._do_play(self._pending_position_ms)

    def _on_error(self, _error, message: str = "") -> None:
        self._ready = False
        self._pending_play = False
        err = message or "音频加载失败"
        self.media_error.emit(err)
