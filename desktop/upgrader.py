"""Animated upgrader gauge. The server chooses outcomes; painting never rerolls."""
import math
import time

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QPolygonF, QRadialGradient,
)
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from challenge_base import ChallengeWindow
from protocol import UPGRADER_FILL_SECONDS, UPGRADER_HOLD_SECONDS


class UpgradeWheel(QWidget):
    """A 400-unit vector canvas keeps the reference proportions at any DPI."""

    def __init__(self, special, chance=50, target_half_width=8):
        super().__init__()
        self.angle = 90.0  # Clockwise from the right; the pointer starts at the bottom.
        self.special = bool(special)
        self.chance = max(0.0, min(100.0, float(chance)))
        self.target_half_width = max(0.1, min(30.0, float(target_half_width)))
        self.result = None
        self.result_progress = 0.0
        self.setMinimumSize(180, 180)

    @staticmethod
    def _polygon(points):
        return QPolygonF([QPointF(x, y) for x, y in points])

    @staticmethod
    def _text(p, box, text, size, color, weight=QFont.Weight.Bold):
        font = QFont('Segoe UI')
        font.setPixelSize(size)
        font.setWeight(weight)
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _emblem(self, p):
        """Custom bevelled R monogram: vector geometry stays sharp at any DPI."""
        p.save()
        orange = QLinearGradient(147, 105, 242, 224)
        orange.setColorAt(0, QColor('#fff0a1'))
        orange.setColorAt(.3, QColor('#ffbb35'))
        orange.setColorAt(.65, QColor('#f0790d'))
        orange.setColorAt(1, QColor('#aa3807'))
        p.setPen(QPen(QColor('#ac6726'), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for points in (
            [(148, 132), (136, 139), (136, 192), (153, 208)],
            [(250, 132), (262, 139), (262, 192), (245, 208)],
        ):
            p.drawPolyline(self._polygon(points))
        mark = QPainterPath()
        mark.setFillRule(Qt.FillRule.OddEvenFill)
        mark.addPolygon(self._polygon([
            (161, 110), (223, 110), (245, 130), (240, 160),
            (220, 176), (247, 222), (215, 222), (190, 179),
            (181, 179), (176, 222), (145, 222),
        ]))
        mark.closeSubpath()
        mark.addPolygon(self._polygon([
            (187, 134), (211, 134), (217, 140), (215, 151),
            (207, 156), (184, 156),
        ]))
        mark.closeSubpath()
        # Offset dark extrusion and thin luminous edges add depth without a font dependency.
        p.translate(0, 4)
        p.fillPath(mark, QColor('#542506'))
        p.translate(0, -4)
        p.setPen(QPen(QColor('#f9b24c'), .85))
        p.setBrush(orange)
        p.drawPath(mark)
        p.setPen(QPen(QColor('#ffe5a0'), 1.6))
        p.drawPolyline(self._polygon([(164, 114), (220, 114), (239, 131)]))
        p.setPen(QPen(QColor('#7d300a'), 2))
        p.drawLine(QPointF(195, 181), QPointF(217, 218))
        p.restore()

    def _result_fill(self, p, circle):
        """A rising coloured wave covers the gauge, clipped to its circular face."""
        if not self.result or self.result_progress <= 0:
            return
        progress = min(1.0, self.result_progress)
        success = self.result in ('win', 'immune')
        p.save()
        clip = QPainterPath()
        clip.addEllipse(circle)
        p.setClipPath(clip)
        level = circle.bottom() + 12 - (circle.height() + 24) * progress
        wave = QPainterPath(QPointF(20, 380))
        for x in range(20, 381, 4):
            y = level + math.sin(x / 27 + progress * 7) * 5 * (1 - progress)
            wave.lineTo(x, y)
        wave.lineTo(380, 380)
        wave.closeSubpath()
        colour = QLinearGradient(200, 32, 200, 370)
        colour.setColorAt(0, QColor('#42e5a0' if success else '#ff7370'))
        colour.setColorAt(.48, QColor('#169a65' if success else '#c72d43'))
        colour.setColorAt(1, QColor('#064633' if success else '#640e26'))
        p.fillPath(wave, colour)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(207, 255, 226, 120) if success else QColor(255, 203, 196, 120), 2))
        p.drawPath(wave)
        p.setPen(QPen(QColor(223, 255, 231, round(70 * progress)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(200, 200), 117, 117)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        p.translate((self.width() - side) / 2, (self.height() - side) / 2)
        p.scale(side / 400, side / 400)
        center = QPointF(200, 200)

        # Muted blue/olive haze echoes the supplied background without screen capture.
        background = QLinearGradient(30, 0, 340, 400)
        background.setColorAt(0, QColor('#485660'))
        background.setColorAt(.44, QColor('#414c4b'))
        background.setColorAt(1, QColor('#565343'))
        p.fillRect(QRectF(0, 0, 400, 400), background)
        for x, y, radius, color in (
            (45, 40, 155, '#687478'), (320, 82, 180, '#899081'),
            (340, 327, 130, '#6f6e59'), (67, 282, 110, '#304248'),
        ):
            fog = QRadialGradient(QPointF(x, y), radius)
            fog.setColorAt(0, QColor(color))
            fog.setColorAt(1, QColor(60, 68, 63, 0))
            p.fillRect(QRectF(0, 0, 400, 400), fog)

        # Outer graduations remain outside the wheel, including below the pointer.
        for tick in range(120):
            a = math.radians(tick * 3)
            direction = QPointF(math.cos(a), math.sin(a))
            major = tick % 10 == 0
            p.setPen(QPen(QColor(211, 216, 193, 100 if major else 42), 1.5 if major else 1))
            p.drawLine(center + direction * 176, center + direction * (193 if major else 183))

        rim = QLinearGradient(40, 30, 350, 380)
        rim.setColorAt(0, QColor('#829080'))
        rim.setColorAt(.28, QColor('#485459'))
        rim.setColorAt(.75, QColor('#656955'))
        rim.setColorAt(1, QColor('#a6a281'))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rim)
        p.drawEllipse(center, 176, 176)
        dark = QLinearGradient(80, 25, 230, 335)
        dark.setColorAt(0, QColor('#0b0e0f'))
        dark.setColorAt(1, QColor('#1b1d18'))
        p.setBrush(dark)
        circle = QRectF(32, 32, 336, 336)
        p.drawEllipse(circle)

        # A wider chance makes the bottom orange sector wider, including >50%.
        sweep = 360.0 * self.chance / 100.0
        lower = QLinearGradient(200, 92, 200, 370)
        lower.setColorAt(0, QColor('#ff9e08'))
        lower.setColorAt(.47, QColor('#dd7400'))
        lower.setColorAt(.72, QColor('#b64600'))
        lower.setColorAt(1, QColor('#770f00'))
        p.setBrush(lower)
        if sweep >= 360:
            p.drawEllipse(circle)
        elif sweep > 0:
            p.drawPie(circle, round((-90.0 - sweep / 2) * 16), round(sweep * 16))

        if self.special:
            bonus = QLinearGradient(200, 308, 200, 369)
            bonus.setColorAt(0, QColor('#e99c12'))
            bonus.setColorAt(.6, QColor('#ffc84a'))
            bonus.setColorAt(1, QColor('#bb7b14'))
            p.setBrush(bonus)
            p.setPen(QPen(QColor('#ffe598'), 1.1))
            p.drawPie(circle, round((-90 - self.target_half_width) * 16),
                      round(self.target_half_width * 32))

        # Double recessed dark rims cover the pies and form the annular chance zone.
        p.setPen(QPen(QColor('#414339'), 5))
        p.setBrush(QColor('#20221e'))
        p.drawEllipse(center, 119, 119)
        p.setPen(QPen(QColor('#131610'), 3))
        inner = QRadialGradient(QPointF(190, 179), 116)
        inner.setColorAt(0, QColor('#252820'))
        inner.setColorAt(1, QColor('#111512'))
        p.setBrush(inner)
        p.drawEllipse(center, 112, 112)
        self._result_fill(p, circle)
        self._emblem(p)

        self._text(p, QRectF(159, 42, 82, 23), '100%', 14, '#525750')
        self._text(p, QRectF(33, 179, 45, 23), '50%', 14, '#89846a')
        self._text(p, QRectF(321, 179, 45, 23), '50%', 14, '#89846a')
        if self.special:
            self._text(p, QRectF(184, 314, 32, 29), '?', 25, '#fff1a0')

        # A subtle text shadow preserves readability over the emblem.
        chance_text = f'{self.chance:.2f}%'
        self._text(p, QRectF(65, 230, 272, 44), chance_text, 34, '#241607')
        self._text(p, QRectF(64, 228, 272, 44), chance_text, 34, '#ffffff')
        caption = ('Без шанса' if self.chance == 0 else 'Гарантированный шанс' if self.chance == 100
                   else 'Низкий шанс' if self.chance < 35 else 'Средний шанс' if self.chance < 65
                   else 'Высокий шанс')
        if self.result:
            caption = {'win': 'УСПЕШНО', 'loss': 'НЕУДАЧА', 'immune': 'ИММУНИТЕТ'}[self.result]
        self._text(p, QRectF(77, 266, 246, 25), caption, 15, '#eee7d2')

        # Short external gold pointer. Its tip points into the selected sector.
        p.save()
        p.translate(center)
        p.rotate(self.angle - 90)
        arrow = self._polygon([(0, 140), (19, 181), (0, 171), (-19, 181)])
        glow = QRadialGradient(QPointF(0, 160), 32)
        glow.setColorAt(0, QColor(255, 187, 0, 125))
        glow.setColorAt(1, QColor(255, 161, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(0, 162), 35, 35)
        pointer = QLinearGradient(0, 144, 0, 181)
        pointer.setColorAt(0, QColor('#fff376'))
        pointer.setColorAt(.5, QColor('#ffb000'))
        pointer.setColorAt(1, QColor('#e45600'))
        p.setPen(QPen(QColor('#64452a'), 6, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(pointer)
        p.drawPolygon(arrow)
        p.setPen(QPen(QColor('#ffe278'), 2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(arrow)
        p.restore()


class Upgrader(ChallengeWindow):
    screen_height_fraction = .5
    FILL_SECONDS = UPGRADER_FILL_SECONDS
    RESULT_HOLD_SECONDS = UPGRADER_HOLD_SECONDS

    def __init__(self, roll, duration):
        super().__init__('Апгрейдер')
        self.roll = roll
        self.spin_seconds = max(1.0, float(duration))
        self.duration = self.spin_seconds + self.FILL_SECONDS + self.RESULT_HOLD_SECONDS
        self.started = 0
        self.result_hold_started = None
        self.setStyleSheet('''
            QWidget#root { background: #111717; border: 1px solid #58635c; }
            QLabel { color: #d6dbce; font-family: "Segoe UI"; border: none; }
            QPushButton { color: #c4c8bb; background: #262d28; border: 1px solid #525b4d;
                          border-radius: 5px; padding: 5px 10px; }
            QPushButton:hover { background: #374133; color: white; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(4)
        header = QHBoxLayout()
        title = QLabel('АПГРЕЙДЕР')
        title.setStyleSheet('font-weight: 700; color: #e8e7d7;')
        header.addWidget(title)
        header.addStretch()
        stop = QPushButton('Отменить · Esc')
        stop.clicked.connect(self.stop)
        header.addWidget(stop)
        layout.addLayout(header)
        self.wheel = UpgradeWheel(roll['special'], roll.get('chance', 50),
                                  roll.get('target_half_width', 8))
        layout.addWidget(self.wheel, 1)
        label = QLabel('Оранжевая зона — победа. Золотой «?» — иммунитет на 10 минут.')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet('font-size: 11px; color: #bfc6b4;')
        layout.addWidget(label)

    def start(self):
        self.started = time.monotonic()
        self.open_window()
        self.start_clock()

    def tick(self):
        if self.done:
            return
        now = time.monotonic()
        elapsed = max(0, now - self.started)
        progress = min(1, elapsed / self.spin_seconds)
        target = 5 * 360 + (self.roll['angle'] - 90) % 360
        self.wheel.angle = 90 + target * (1 - (1 - progress) ** 4)
        if progress >= 1:
            self.wheel.result = self.roll['result']
            self.wheel.result_progress = min(1, (elapsed - self.spin_seconds) / self.FILL_SECONDS)
            if self.wheel.result_progress >= 1 and self.result_hold_started is None:
                # Always give the completed fill two visible seconds, even after a slow frame.
                self.result_hold_started = now
                self.deadline = now + self.RESULT_HOLD_SECONDS
        self.wheel.update()
        if self.result_hold_started is not None and now - self.result_hold_started >= self.RESULT_HOLD_SECONDS:
            result = self.roll['result']
            self.finish(result, {
                'immune': 'Попадание в «?»! Иммунитет от событий на 10 минут.',
                'win': 'Апгрейдер: победа. Dota 2 остаётся открытой.',
                'loss': 'Апгрейдер: стрелка вне зоны победы. Поражение.',
            }[result])
