"""Lightweight quarter-screen survival Pong. No mouse hooks or image scaling."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget, QApplication


@dataclass
class PongModel:
    # Logical coordinates are independent of screen resolution.
    x: float = 500.0
    y: float = 300.0
    vx: float = -260.0
    vy: float = 155.0
    paddle: float = 300.0
    hits: int = 0
    lost: bool = False

    def step(self, dt: float, direction: int):
        # Small physics steps prevent tunnelling through a paddle at low FPS.
        while dt > 0 and not self.lost:
            step = min(dt, 1 / 240)
            dt -= step
            self.paddle = min(540, max(60, self.paddle + direction * 440 * step))
            old_x = self.x
            self.x += self.vx * step
            self.y += self.vy * step
            if self.y < 9:
                self.y, self.vy = 18-self.y, abs(self.vy)
            if self.y > 591:
                self.y, self.vy = 1182-self.y, -abs(self.vy)
            if self.x > 791:
                self.x, self.vx = 1582-self.x, -abs(self.vx)
            if self.vx < 0 and old_x >= 49 and self.x <= 49:
                if abs(self.y-self.paddle) <= 69:
                    self.x = 98-self.x
                    speed = min(430, math.hypot(self.vx, self.vy) + 14)
                    angle = (self.y-self.paddle) / 69 * 1.0
                    self.vx, self.vy = speed * math.cos(angle), speed * math.sin(angle)
                    self.hits += 1
            if self.x < -9:
                self.lost = True


class PongOverlay(QWidget):
    finished = pyqtSignal(str)

    def __init__(self, keys, duration=30.0, screen=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.keys = keys
        self.duration = duration
        self.model = PongModel()
        self.deadline = None
        self.last = None
        self.result = None
        area = (screen or QApplication.primaryScreen()).geometry()
        self.setGeometry(area.x()+area.width()//2, area.y(),
                         area.width()-area.width()//2, area.height()//2)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)

    def start(self):
        self.show()
        self.last = time.monotonic()
        self.deadline = self.last + self.duration
        self.timer.start(16)

    def remaining(self):
        return max(0, self.deadline-time.monotonic()) if self.deadline else 0

    def advance(self):
        if self.result is not None:
            return
        now = time.monotonic()
        keys = self.keys()
        direction = int(0x28 in keys) - int(0x26 in keys)
        # Simulate only time before the deadline, even if the UI timer is late.
        dt = max(0, min(now, self.deadline)-self.last)
        self.model.step(dt, direction)
        self.last = now
        if self.model.lost:
            self.finish('loss')
        elif now >= self.deadline:
            self.finish('win')
        else:
            self.update()

    def finish(self, result):
        if self.result is not None:
            return
        self.result = result
        self.timer.stop()
        self.hide()
        self.finished.emit(result)

    def stop(self):
        self.finish('cancel')

    def closeEvent(self, event):
        self.stop()
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#101827'))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor('#eef5ff'))
        p.setFont(QFont('Segoe UI', 14, QFont.Weight.Bold))
        p.drawText(QRectF(10, 8, self.width()-20, 30), Qt.AlignmentFlag.AlignCenter,
                   f'ПИНГ-ПОНГ  ·  {math.ceil(self.remaining())} СЕК')
        p.setFont(QFont('Segoe UI', 9))
        p.drawText(QRectF(10, 40, self.width()-20, 40), Qt.AlignmentFlag.AlignCenter,
                   '↑ / ↓ — ракетка  ·  F12 — выход\nВыдержи 30 секунд. Промах — закрытие Dota 2.')
        p.translate(12, 88)
        p.scale(max(1, self.width()-24)/800, max(1, self.height()-102)/600)
        p.setPen(QPen(QColor('#485979'), 3))
        p.drawRect(QRectF(0, 0, 800, 600))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#75e8c5'))
        p.drawRoundedRect(QRectF(26, self.model.paddle-60, 14, 120), 5, 5)
        p.setBrush(QColor('#fff1b1'))
        p.drawEllipse(QRectF(self.model.x-9, self.model.y-9, 18, 18))
