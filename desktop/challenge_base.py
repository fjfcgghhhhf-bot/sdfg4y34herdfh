"""Shared bounded lifetime for interactive challenges (Qt GUI thread only)."""
import time
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut, QCursor
from PyQt6.QtWidgets import QWidget, QApplication, QLabel


class DragHeader(QLabel):
    """Drag only the header, so board clicks and chat text selection stay intact."""
    def __init__(self, window, title):
        super().__init__('⠿  '+title, window)
        self.owner=window; self.offset=None
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('Перетащите окно за эту панель в любое место экрана.')
        self.setStyleSheet('background:#273449;color:#dcebcf;border-radius:6px;padding:7px;font-weight:600;')

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.offset=event.globalPosition().toPoint()-self.owner.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor); event.accept()
        else: super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint()-self.offset); event.accept()
        else: super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.offset=None; self.setCursor(Qt.CursorShape.OpenHandCursor); event.accept()
        else: super().mouseReleaseEvent(event)


class ChallengeWindow(QWidget):
    finished = pyqtSignal(str, str)
    screen_height_fraction = 1.0

    def __init__(self, title):
        # Unlike video, these overlays accept clicks and typing.
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName('root')
        self.setWindowTitle(title)
        self.deadline = None
        self.duration = 60.0
        self.done = False
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.tick)
        self.escape = QShortcut(QKeySequence('Escape'), self)
        self.escape.activated.connect(self.stop)

    def start_clock(self):
        self.deadline = time.monotonic()+self.duration
        self.timer.start()

    def add_drag_header(self,layout,title=None):
        self.drag_header=DragHeader(self,title or self.windowTitle())
        layout.addWidget(self.drag_header)
        return self.drag_header

    def remaining(self):
        return max(0, self.deadline-time.monotonic()) if self.deadline and not self.done else 0

    def open_window(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.geometry()
        self.setGeometry(area.x()+area.width()//2, area.y(),
                         area.width()-area.width()//2, int(area.height()*self.screen_height_fraction))
        self.show()
        self.raise_()
        self.activateWindow()

    def cleanup(self):
        pass

    def finish(self, result, reason):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        self.cleanup()
        self.hide()
        self.finished.emit(result, reason)

    def stop(self):
        self.finish('cancel', 'Событие отменено. Dota 2 остаётся открытой.')

    def closeEvent(self, event):
        self.stop()
        event.accept()
