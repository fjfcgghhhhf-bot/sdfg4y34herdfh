"""Animated upgrader gauge. The server chooses outcomes; painting never rerolls."""
import math
import time

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen,
    QPolygonF, QRadialGradient,
)
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from challenge_base import ChallengeWindow


class UpgradeWheel(QWidget):
    """A 400-unit vector canvas keeps the reference proportions at any DPI."""

    def __init__(self, special, chance=50, target_half_width=8):
        super().__init__()
        self.angle = 90.0  # Clockwise from the right; the pointer starts at the bottom.
        self.special = bool(special)
        self.chance = max(0.0, min(100.0, float(chance)))
        self.target_half_width = max(0.1, min(30.0, float(target_half_width)))
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
        """Angular orange animal emblem, built from paths rather than a bitmap."""
        orange = QLinearGradient(120, 100, 268, 303)
        orange.setColorAt(0, QColor('#ef7a13'))
        orange.setColorAt(.55, QColor('#c5570a'))
        orange.setColorAt(1, QColor('#993804'))
        p.setPen(QPen(QBrush(orange), 3.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Two broken angular shields surround the animal head.
        for points in (
            [(121, 168), (121, 153), (132, 145)],
            [(170, 117), (199, 101), (280, 146), (280, 192)],
            [(183, 119), (199, 111), (270, 152), (270, 182)],
            [(126, 225), (119, 228), (119, 241), (198, 287), (208, 280)],
            [(136, 228), (128, 234), (199, 276), (204, 272)],
            [(153, 240), (191, 262)],
        ):
            p.drawPolyline(self._polygon(points))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(orange))
        # Long ears, swept mane, pointed muzzle and a hanging angular lower jaw.
        p.drawPolygon(self._polygon([
            (147, 151), (139, 117), (179, 148), (166, 119),
            (195, 138), (188, 121), (224, 153), (217, 135),
            (249, 166), (251, 181), (268, 192), (280, 211),
            (271, 211), (289, 235), (278, 230), (275, 241),
            (265, 230), (252, 229), (235, 218), (237, 249),
            (232, 245), (236, 273), (220, 279), (209, 233),
            (197, 221), (175, 218), (169, 225), (156, 207),
            (133, 217), (143, 199), (113, 205), (130, 188),
            (110, 182), (131, 164),
        ]))
        # Negative-space facets keep the mark crisp behind the percentage.
        p.setBrush(QColor('#141714'))
        for points in (
            [(146, 130), (153, 156), (176, 158)],
            [(154, 164), (184, 160), (171, 176)],
            [(192, 150), (220, 160), (229, 176), (209, 167)],
            [(232, 183), (247, 192), (239, 195)],
            [(197, 216), (215, 222), (223, 259), (216, 245)],
            [(139, 204), (157, 199), (169, 212), (155, 207)],
        ):
            p.drawPolygon(self._polygon(points))

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
        self._emblem(p)

        self._text(p, QRectF(159, 42, 82, 23), '100%', 14, '#525750')
        self._text(p, QRectF(33, 179, 45, 23), '50%', 14, '#89846a')
        self._text(p, QRectF(321, 179, 45, 23), '50%', 14, '#89846a')
        if self.special:
            self._text(p, QRectF(184, 314, 32, 29), '?', 25, '#fff1a0')

        # A subtle text shadow preserves readability over the emblem.
        chance_text = f'{self.chance:.2f}%'
        self._text(p, QRectF(65, 162, 272, 51), chance_text, 37, '#241607')
        self._text(p, QRectF(64, 160, 272, 51), chance_text, 37, '#ffffff')
        caption = ('Без шанса' if self.chance == 0 else 'Гарантированный шанс' if self.chance == 100
                   else 'Низкий шанс' if self.chance < 35 else 'Средний шанс' if self.chance < 65
                   else 'Высокий шанс')
        self._text(p, QRectF(77, 205, 246, 29), caption, 18, '#eee7d2')

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

    def __init__(self, roll, duration):
        super().__init__('Апгрейдер')
        self.roll = roll
        self.duration = max(1.0, float(duration))
        self.started = 0
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
        # Stop on the server angle, then hold it for 700 ms before finishing.
        progress = max(0, min(1, (time.monotonic() - self.started) / (self.duration - .7)))
        target = 5 * 360 + (self.roll['angle'] - 90) % 360
        self.wheel.angle = 90 + target * (1 - (1 - progress) ** 4)
        self.wheel.update()
        if self.remaining() <= 0:
            result = self.roll['result']
            self.finish(result, {
                'immune': 'Попадание в «?»! Иммунитет от событий на 10 минут.',
                'win': 'Апгрейдер: победа. Dota 2 остаётся открытой.',
                'loss': 'Апгрейдер: стрелка вне зоны победы. Поражение.',
            }[result])
