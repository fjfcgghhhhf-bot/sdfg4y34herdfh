"""Bounded, click-through video overlay for Debuff Roulette.

All methods must be called on the Qt GUI thread. This module only reads the
selected local video. It does not change display power, system settings, or
global audio volume. QAudioOutput controls this player's own volume.
"""

from __future__ import annotations

import math
from pathlib import Path
import time

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QScreen
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class VideoOverlay(QWidget):
    """Play local video with audio on the right half of one screen.

    ``started`` fires when the first valid video frame arrives. The duration
    counts wall-clock time from that frame, including any later buffering.
    Loading is bounded separately, so a broken codec/file cannot leave a
    persistent black overlay. ``finished`` fires once for every started
    request, including cancellation and failure. ``failed`` precedes it on
    failure. The main application should connect emergency exit to ``stop``.

    This is a fixed, opaque overlay. It passes input through to the game and
    does not activate its window. Use Dota's borderless/windowed display mode
    because a desktop overlay cannot guarantee visibility over exclusive
    fullscreen output.
    """

    started = pyqtSignal()
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    LOAD_TIMEOUT_MS = 12_000

    def __init__(
        self,
        path: Path,
        duration: float = 30.0,
        volume: float = 0.65,
        screen: QScreen | None = None,
    ) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Длительность видео должна быть положительным числом")
        if not math.isfinite(volume) or not 0.0 <= volume <= 1.0:
            raise ValueError("Громкость должна быть от 0 до 1")

        self.path = Path(path).expanduser().resolve()
        self.duration = float(duration)
        self._requested = False
        self._deadline: float | None = None
        self._screen = screen or QApplication.primaryScreen()
        if self._screen is None:
            raise RuntimeError("Экран для видео недоступен")

        self.setWindowTitle("Рулетка дебаффов — Видео")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setStyleSheet("background: #080910; color: #f5f4ff;")

        # Logical screen coordinates keep the overlay on the selected monitor
        # under Windows display scaling and on monitors with negative origins.
        rect = self._screen.geometry()
        half = rect.width() // 2
        self.setGeometry(rect.x() + half, rect.y(), rect.width() - half, rect.height())

        self.caption = QLabel(self)
        self.caption.setStyleSheet(
            "background: #161426; color: #e5dbff; padding: 10px 14px;"
            "font-family: 'Segoe UI'; font-size: 13px; font-weight: 600;"
        )
        self.caption.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.video = QVideoWidget(self)
        self.video.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.video.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.caption)
        layout.addWidget(self.video, 1)

        self.audio = QAudioOutput(self)
        self.audio.setVolume(volume)
        self.audio.setMuted(True)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QMediaPlayer.Loops.Infinite.value)
        self.player.errorOccurred.connect(self._media_error)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.video.videoSink().videoFrameChanged.connect(self._first_frame)

        self._load_timer = QTimer(self)
        self._load_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._load_timeout)
        self._end_timer = QTimer(self)
        self._end_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._end_timer.setSingleShot(True)
        self._end_timer.timeout.connect(self._deadline_reached)
        self._caption_timer = QTimer(self)
        self._caption_timer.setInterval(100)
        self._caption_timer.timeout.connect(self._update_caption)

        # This also covers normal application exit, in addition to F12's
        # explicit stop() call. Media is not left running in a hidden window.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def start(self) -> None:
        """Request playback; repeated calls while active have no effect."""
        if self._requested:
            return
        self._requested = True
        self._deadline = None
        if not self.path.is_file():
            self._finish(f"Видеофайл не найден: {self.path}")
            return
        self.audio.setMuted(True)
        self._load_timer.start(self.LOAD_TIMEOUT_MS)
        self.player.setSource(QUrl.fromLocalFile(str(self.path)))
        # setSource may synchronously report an error on some Qt backends.
        if self._requested:
            self.player.play()

    def stop(self) -> None:
        """Immediately hide, silence, and release playback resources."""
        self._finish()

    def remaining(self) -> float:
        """Return playback seconds left (full duration while loading)."""
        if not self._requested:
            return 0.0
        if self._deadline is None:
            return self.duration
        return max(0.0, self._deadline - time.monotonic())

    def _first_frame(self, frame: QVideoFrame) -> None:
        if not self._requested or self._deadline is not None or not frame.isValid():
            return
        self._deadline = time.monotonic() + self.duration
        self._load_timer.stop()
        self._update_caption()
        self.show()
        self.audio.setMuted(False)
        self._caption_timer.start()
        self._end_timer.start(max(1, math.ceil(self.duration * 1000)))
        self.started.emit()

    def _deadline_reached(self) -> None:
        if not self._requested or self._deadline is None:
            return
        left = self.remaining()
        if left > 0:
            # Never finish early if the timer/event loop rounds a deadline.
            self._end_timer.start(max(1, math.ceil(left * 1000)))
        else:
            self.stop()

    def _update_caption(self) -> None:
        self.caption.setText(
            f"РУЛЕТКА ДЕБАФФОВ  •  ВИДЕО {math.ceil(self.remaining()):02d} СЕК"
            "        F12 — АВАРИЙНЫЙ ВЫХОД"
        )

    def _load_timeout(self) -> None:
        if self._requested and self._deadline is None:
            self._finish("Видео не загрузилось за 12 секунд")

    def _media_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if self._requested and error != QMediaPlayer.Error.NoError:
            self._finish("Не удалось воспроизвести видео. Проверьте файл и кодек.")

    def _media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._requested and status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._finish("Файл повреждён или формат не поддерживается")

    def _finish(self, error: str | None = None) -> None:
        was_requested = self._requested
        # Clear state before stopping the player: stop/setSource can emit
        # media callbacks synchronously, and those must not restart anything.
        self._requested = False
        self._deadline = None
        self._load_timer.stop()
        self._end_timer.stop()
        self._caption_timer.stop()
        self.hide()
        self.audio.setMuted(True)
        self.player.stop()
        self.player.setSource(QUrl())
        if was_requested:
            if error:
                self.failed.emit(error)
            self.finished.emit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop()
        event.accept()
