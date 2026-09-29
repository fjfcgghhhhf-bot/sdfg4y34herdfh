"""Forty-second click-through overlay; four bouncing cubes, five seconds each."""
from dataclasses import dataclass
import math
import random
import time

from PyQt6.QtCore import Qt, QTimer, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPolygonF
from PyQt6.QtWidgets import QWidget, QApplication


@dataclass
class Cube:
    born: float
    size: float
    x: float
    speed: float
    floor: float
    jump: float
    period: float

    def position(self, now, width):
        age = max(0, now-self.born)
        limit = max(1, width-self.size)
        phase = (self.x+self.speed*age) % (2*limit)
        x = limit-abs(phase-limit)
        y = self.floor - abs(math.sin(age*math.pi/self.period))*self.jump
        return x, y


class CubesModel:
    def __init__(self, width, height, started, duration=40.0, rng=None):
        self.width, self.height = width, height
        self.deadline = started+duration
        self.next_spawn = started
        self.cubes = []
        self.rng = rng or random.Random()

    def advance(self, now):
        self.cubes = [c for c in self.cubes if now-c.born < 5.0]
        if now >= self.deadline:
            self.cubes.clear()
            return
        if now >= self.next_spawn and now <= self.deadline-5 and len(self.cubes) < 4:
            r = self.rng
            size = r.uniform(.075, .19)*min(self.width, self.height)
            floor = r.uniform(.55, 1)*(self.height-size)
            self.cubes.append(Cube(now, size, r.uniform(0, self.width-size),
                                   r.choice((-1, 1))*r.uniform(170, 420), floor,
                                   r.uniform(.25, .85)*floor, r.uniform(.65, 1.3)))
            self.next_spawn = now+1.25


class RedCubes(QWidget):
    finished = pyqtSignal()

    def __init__(self, screen=None, duration=40.0):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry((screen or QApplication.primaryScreen()).geometry())
        self.model = None
        self.duration = duration
        self.done = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)

    def start(self):
        self.model = CubesModel(self.width(), self.height(), time.monotonic(), self.duration)
        self.show()
        self.advance()
        self.timer.start(33)

    def remaining(self):
        return max(0, self.model.deadline-time.monotonic()) if self.model and not self.done else 0

    def advance(self):
        now = time.monotonic()
        self.model.advance(now)
        if now >= self.model.deadline:
            self.stop()
        else:
            self.update()

    def stop(self):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        if self.model:
            self.model.cubes.clear()
        self.hide()
        self.finished.emit()

    def closeEvent(self, event):
        # No title bar, focus, draggable area or user-closeable cube windows.
        if self.done: event.accept()
        else: event.ignore()

    def paintEvent(self, event):
        if not self.model:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        now = time.monotonic()
        for cube in self.model.cubes:
            if now-cube.born >= 5:
                continue
            x,y = cube.position(now, self.width())
            s = cube.size
            for color, points in (
                ('#ff5959', ((0,.22),(.22,0),(1,0),(.78,.22))),
                ('#a81224', ((.78,.22),(1,0),(1,.78),(.78,1))),
                ('#eb263b', ((0,.22),(.78,.22),(.78,1),(0,1))),
            ):
                p.setBrush(QColor(color))
                p.drawPolygon(QPolygonF([QPointF(x+a*s,y+b*s) for a,b in points]))
