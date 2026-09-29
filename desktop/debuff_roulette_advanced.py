"""Advanced Рулетка дебаффов. Windows/PyQt6. Run paused, then enable the timer.

Effects use temporary input hooks, guarded display rotation and local video.
No OS settings are persisted. See advanced_input.py for the safety thread.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import multiprocessing
from dataclasses import dataclass
import math
from pathlib import Path
import queue
import random
import sys
import threading
import time

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QTranslator, QLocale
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QCursor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSlider,
    QVBoxLayout, QWidget, QScrollArea, QComboBox,
)

from advanced_input import WindowsController
from video_overlay import VideoOverlay
from screen_rotation import ScreenRotation
from cmd_event import CmdEvent
from monitor_power import MonitorPower
from pong_overlay import PongOverlay
from red_cubes import RedCubes
from desktop_event import DesktopSwitch
from chess_event import ChessChallenge
from ai_event import AIChallenge, DEFAULT_MODEL
from app_secrets import GROQ_API_KEY


INTERVAL = 120.0
SPIN_SECONDS = 3.2


@dataclass(frozen=True)
class Effect:
    kind: str
    title: str
    wheel: str
    seconds: int
    color: str


EFFECTS = (
    Effect("swap", "Поменять кнопки мыши", "СМЕНА\nКНОПОК", 20, "#6860b4"),
    Effect("invert", "Инверсия движения мыши", "ИНВЕРСИЯ\nМЫШИ", 20, "#267d8a"),
    Effect("tp", "ТП на базу + блок ввода", "ТП\nНА БАЗУ", 6, "#b1793b"),
    Effect("window", "Смена окна + блок клавиатуры и мыши", "СМЕНА\nОКНА", 5, "#aa507a"),
    Effect("video", "Видео поверх половины экрана", "ВИДЕО\nОВЕРЛЕЙ", 30, "#b94f5f"),
    Effect("keyboard", "Блокировка клавиатуры", "БЛОК\nКЛАВИШ", 3, "#6b4aa4"),
    Effect("mouse", "Блокировка мыши", "БЛОК\nМЫШИ", 3, "#28657c"),
    Effect("both", "Блокировка клавиатуры и мыши", "БЛОК\nВВОДА", 3, "#64773d"),
    Effect("kill", "Закрыть Dota 2", "ЗАКРЫТЬ\nDOTA 2", 0, "#ab3d45"),
    Effect("buy", "Купить случайно 1–10 ТП", "КУПИТЬ\n1–10 ТП", 0, "#89753a"),
    Effect("reverse", "Переворот экрана", "ПЕРЕВОРОТ\nЭКРАНА", 30, "#357b70"),
    Effect("cmd", "Консоль по центру экрана", "КОНСОЛЬ", 10, "#407d42"),
    Effect("monitor", "Выключение монитора", "МОНИТОР\nВЫКЛ", 10, "#535669"),
    Effect("pong", "Пинг-понг · 1 на 1", "ПИНГ\nПОНГ", 0, "#317cad"),
    Effect("desktop", "Перейти на второй рабочий стол", "РАБОЧИЙ\nСТОЛ 2", 0, "#5864a2"),
    Effect("cubes", "Красные кубы — прыгающие кубы", "КРАСНЫЕ\nКУБЫ", 40, "#b63447"),
    Effect("chess", "Шахматы · 1 на 1", "ШАХМАТЫ", 0, "#607b81"),
    Effect("ai", "Убеди ИИ — растущий накал", "УБЕДИ\nИИ", 60, "#9262b0"),
    Effect("upgrader", "Апгрейдер", "АПГРЕЙДЕР", 7, "#c44883"),
    Effect("music", "Музыка", "МУЗЫКА", 60, "#328b85"),
    Effect("bw", "Чёрно-белый экран", "ЧБ ЭКРАН", 60, "#697384"),
)

WHEEL_LABELS = {'swap':'Кнопки', 'invert':'Инверсия', 'tp':'ТП на базу',
                'window':'Смена окна', 'video':'Видео', 'keyboard':'Клавиатура',
                'mouse':'Мышь', 'both':'Блок ввода', 'kill':'Закрыть Dota',
                'buy':'Купить ТП', 'reverse':'Переворот', 'cmd':'Консоль',
                'monitor':'Монитор', 'pong':'Пинг-понг', 'desktop':'Стол 2',
                'cubes':'Кубы', 'chess':'Шахматы', 'ai':'Убеди ИИ',
                'upgrader':'Апгрейдер', 'music':'Музыка', 'bw':'ЧБ экран'}


def bundled_video() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "roulette_video.mp4"


STYLE = """
QMainWindow, QWidget#root { background: #111522; color: #edf0fa; }
QLabel { color: #edf0fa; }
QFrame#card { background: #1b2134; border: 1px solid #2a334d; border-radius: 12px; }
QLabel#muted { color: #9ba8c5; }
QLabel#eyebrow { color: #c697ff; font-size: 12px; font-weight: 700; }
QLabel#timer { color: #72debf; font-size: 42px; font-weight: 700; }
QLabel#active { font-size: 16px; font-weight: 600; }
QPushButton { background: #323c58; color: #f5f6ff; border: none;
              border-radius: 7px; padding: 10px 13px; font-weight: 600; }
QPushButton:hover { background: #445171; }
QPushButton:pressed { background: #252d44; }
QPushButton:disabled { background: #22293c; color: #68758f; }
QPushButton#primary { background: #6952a5; }
QPushButton#primary:hover { background: #7d65bc; }
QPushButton#panic { background: #883f51; }
QPushButton#panic:hover { background: #a54a61; }
QCheckBox { color: #edf0fa; spacing: 8px; padding: 3px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #687397;
                       border-radius: 3px; background: #222b42; }
QCheckBox::indicator:checked { background: #a278db; border: 1px solid #c8a2ff; }
QLineEdit { color: #edf0fa; background: #111829; border: 1px solid #3d4966;
            border-radius: 5px; padding: 7px; }
QSlider::groove:horizontal { height: 5px; background: #364460; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #aa85e1; }
QToolTip { background: #20293d; color: white; border: 1px solid #65708c; }
QComboBox { background: #323c58; color: white; padding: 6px; }
QComboBox QAbstractItemView { background: #20293d; color: white; selection-background-color: #6952a5; }
QProgressBar { border: 1px solid #546385; color: white; text-align: center; min-height: 24px; }
QProgressBar::chunk { background: #9253a0; }
"""


class RouletteWheel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.angle = 0.0
        self.enabled = [True] * len(EFFECTS)
        self.setMinimumSize(350, 350)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2 + 5
        radius = min(self.width(), self.height()) / 2 - 27
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        painter.setBrush(QColor("#121828"))
        painter.setPen(QPen(QColor("#546385"), 2))
        painter.drawEllipse(rect.adjusted(-7, -7, 7, 7))
        step = 360 / len(EFFECTS)
        for index, effect in enumerate(EFFECTS):
            start = self.angle + index * step
            painter.setBrush(QColor(effect.color if self.enabled[index] else "#303b52"))
            painter.setPen(QPen(QColor("#171e30"), 3))
            painter.drawPie(rect, round(start * 16), round(step * 16))
            radians = math.radians(start + step / 2)
            px = cx + math.cos(radians) * radius * 0.75
            py = cy - math.sin(radians) * radius * 0.75
            painter.setPen(QColor("#ffffff"))
            font = QFont("Segoe UI", 8, QFont.Weight.Bold)
            font.setPixelSize(max(8, min(13, round(radius*.065))))
            painter.setFont(font)
            painter.save()
            painter.translate(px, py)
            mid = (start+step/2) % 360
            painter.rotate(-mid + (180 if 90 < mid < 270 else 0))
            painter.drawText(QRectF(-radius*.26, -10, radius*.52, 20),
                             Qt.AlignmentFlag.AlignCenter, WHEEL_LABELS[effect.kind])
            painter.restore()
        painter.setBrush(QColor("#111522"))
        painter.setPen(QPen(QColor("#d2b6fb"), 3))
        painter.drawEllipse(QPointF(cx, cy), 64, 64)
        painter.setPen(QColor("#eef0fa"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        painter.drawText(QRectF(cx-60, cy-40, 120, 80), Qt.AlignmentFlag.AlignCenter,
                         "DOTA 2\nРУЛЕТКА")
        top = cy - radius
        painter.setPen(QPen(QColor("#151a28"), 2))
        painter.setBrush(QColor("#ffdf96"))
        painter.drawPolygon(QPolygonF([QPointF(cx-14, top-18),
                                       QPointF(cx+14, top-18), QPointF(cx, top+14)]))


class MainWindow(QMainWindow):
    def __init__(self, demo: bool = False, video: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Рулетка дебаффов — Dota 2")
        self.resize(1200, 900)
        self.setMinimumSize(1000, 760)
        self.controller = WindowsController()
        self.cancel = threading.Event()
        self.messages: queue.Queue[tuple[threading.Event, str]] = queue.Queue()
        self.running = False
        self.closed = False
        self.next_spin = time.monotonic() + INTERVAL
        self.spin: tuple[int, float, float, float] | None = None
        self.overlay: VideoOverlay | None = None
        self.rotation = ScreenRotation()
        self.cmd_event = CmdEvent()
        self.monitor = MonitorPower()
        self.pong: PongOverlay | None = None
        self.cubes: RedCubes | None = None
        self.desktop = DesktopSwitch()
        self.challenge = None
        self.video_path = video if video is not None else bundled_video()
        self.effect_title = "Ожидание запуска"
        self.had_effect = False
        self.last_focus_check = 0.0
        self.build_ui(demo)
        try:
            self.controller.start()
        except Exception:
            self.controller.close()
            raise
        self.tick_timer = QTimer(self)
        self.tick_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(25)

    def label(self, text: str, name: str = "", wrap: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(wrap)
        return label

    def button(self, text: str, action, name: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(action)
        return button

    def build_ui(self, demo: bool) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(15)
        header = QHBoxLayout()
        title = self.label("РУЛЕТКА ДЕБАФФОВ")
        title.setFont(QFont("Segoe UI", 23, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.label("ВЕРСИЯ 11  /  18 ЭФФЕКТОВ", "eyebrow"))
        outer.addLayout(header)
        columns = QHBoxLayout()
        columns.setSpacing(20)
        outer.addLayout(columns, 1)
        left = QVBoxLayout()
        left.setSpacing(12)
        columns.addLayout(left, 1)
        wheel_card = QFrame()
        wheel_card.setObjectName("card")
        wheel_layout = QVBoxLayout(wheel_card)
        wheel_layout.setContentsMargins(8, 4, 8, 12)
        self.wheel = RouletteWheel()
        wheel_layout.addWidget(self.wheel, 1)
        self.active_label = self.label(self.effect_title, "active", True)
        self.active_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wheel_layout.addWidget(self.active_label)
        left.addWidget(wheel_card, 1)
        video_card = QFrame()
        video_card.setObjectName("card")
        vl = QVBoxLayout(video_card)
        vl.setContentsMargins(14, 10, 14, 12)
        vl.addWidget(self.label("ВИДЕО СО ЗВУКОМ · ПОЛОВИНА ЭКРАНА · 30 СЕК", "eyebrow"))
        file_row = QHBoxLayout()
        self.video_label = QLineEdit(self.video_path.name)
        self.video_label.setReadOnly(True)
        self.video_label.setToolTip(str(self.video_path))
        file_row.addWidget(self.video_label, 1)
        file_row.addWidget(self.button("Выбрать…", self.choose_video))
        vl.addLayout(file_row)
        audio_row = QHBoxLayout()
        audio_row.addWidget(self.label("Звук", "muted"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(65)
        audio_row.addWidget(self.volume, 1)
        self.volume_value = self.label("65%", "muted")
        audio_row.addWidget(self.volume_value)
        self.volume.valueChanged.connect(lambda value: self.volume_value.setText(f"{value}%"))
        audio_row.addWidget(self.button("Предпросмотр", self.preview_video))
        vl.addLayout(audio_row)
        left.addWidget(video_card)
        side_widget = QWidget()
        side_widget.setMinimumWidth(390)
        side = QVBoxLayout(side_widget)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(410)
        scroll.setMaximumWidth(440)
        scroll.setWidget(side_widget)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget {background: #111522;}")
        columns.addWidget(scroll)
        timer_card = QFrame()
        timer_card.setObjectName("card")
        tl = QVBoxLayout(timer_card)
        tl.setContentsMargins(16, 10, 16, 10)
        caption = self.label("ДО СЛЕДУЮЩЕГО ВРАЩЕНИЯ", "muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(caption)
        self.timer_label = self.label("02:00", "timer")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(self.timer_label)
        side.addWidget(timer_card)
        actions = QGridLayout()
        self.start_button = self.button("Запустить", self.start_timer, "primary")
        actions.addWidget(self.start_button, 0, 0)
        actions.addWidget(self.button("Стоп / снять эффект", self.stop_timer), 0, 1)
        actions.addWidget(self.button("Крутить сейчас", self.begin_spin), 1, 0, 1, 2)
        side.addLayout(actions)
        side.addWidget(self.label("Эффекты работают во всех окнах. ТП и покупка сами открывают Dota 2.", "muted", True))
        side.addWidget(self.label("ЭФФЕКТЫ И ДЛИТЕЛЬНОСТЬ", "eyebrow"))
        self.checks: list[QCheckBox] = []
        for effect in EFFECTS:
            check = QCheckBox(effect.title + (f" · {effect.seconds} с" if effect.seconds else ""))
            check.setChecked(effect.kind not in ("kill", "buy"))
            check.setToolTip(effect.title)
            check.stateChanged.connect(self.refresh_sectors)
            self.checks.append(check)
            side.addWidget(check)
        tp_row = QHBoxLayout()
        tp_row.addWidget(self.label("Клавиша слота ТП", "muted"))
        tp_row.addStretch()
        self.tp_key = QLineEdit("T")
        self.tp_key.setMaxLength(1)
        self.tp_key.setFixedWidth(55)
        self.tp_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tp_row.addWidget(self.tp_key)
        side.addLayout(tp_row)
        shop_row = QHBoxLayout()
        shop_row.addWidget(self.label("Магазин", "muted"))
        self.shop_key = QLineEdit("F4")
        self.shop_key.setFixedWidth(55)
        shop_row.addWidget(self.shop_key)
        self.shop_xy = QLineEdit()
        self.shop_xy.setPlaceholderText("ТП: x, y")
        shop_row.addWidget(self.shop_xy)
        side.addLayout(shop_row)
        side.addWidget(self.button("Запомнить позицию ТП через 3 секунды", self.capture_shop))
        side.addWidget(self.label("НАСТРОЙКИ ИИ · GROQ", "eyebrow"))
        self.api_key = QLineEdit(os.environ.get('GROQ_API_KEY') or GROQ_API_KEY)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText('Встроенный ключ Groq; можно заменить на этот запуск')
        side.addWidget(self.api_key)
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)
        self.ai_model.addItems([DEFAULT_MODEL, 'openai/gpt-oss-120b'])
        side.addWidget(self.ai_model)
        side.addWidget(self.label('Ключ Groq встроен. В сервис отправляется только переписка мини-игры. '
                                  'Событие «Убеди ИИ» готово к запуску.', 'muted', True))
        self.test_effect = QComboBox()
        for effect in EFFECTS:
            self.test_effect.addItem(effect.title)
        self.test_effect.setStyleSheet("background:#323c58;color:white;padding:7px;")
        side.addWidget(self.test_effect)
        side.addWidget(self.button("Применить выбранный эффект", self.apply_manual))
        self.demo_check = QCheckBox("Демо: без изменения ввода и окон")
        self.demo_check.setChecked(demo)
        self.demo_check.stateChanged.connect(self.stop_timer)
        side.addWidget(self.demo_check)
        side.addStretch()
        outer.addWidget(self.button("Аварийный выход  ·  F12", self.close, "panic"))
        self.focus_label = self.label("ГЛОБАЛЬНЫЙ РЕЖИМ · F12 — ВЫХОД", "eyebrow")
        self.note_label = self.label("Выберите эффекты и нажмите «Запустить». Приложение начинает на паузе.",
                                     "muted", True)
        outer.addWidget(self.focus_label)
        outer.addWidget(self.note_label)
        self.refresh_sectors()

    def capture_shop(self) -> None:
        self.note_label.setText("Откройте магазин и наведите курсор на иконку ТП. Позиция сохранится через 3 секунды.")
        def capture():
            from ctypes import wintypes
            point = wintypes.POINT()
            if self.controller.user.GetCursorPos(ctypes.byref(point)):
                self.shop_xy.setText(f"{point.x}, {point.y}")
                self.note_label.setText("Позиция ТП сохранена. Перед покупкой магазин должен быть закрыт.")
        QTimer.singleShot(3000, capture)

    def apply_manual(self) -> None:
        self.spin = None
        self.stop_effect()
        self.apply_selected(self.test_effect.currentIndex(), manual=True)

    def refresh_sectors(self) -> None:
        self.wheel.enabled = [check.isChecked() for check in self.checks]
        self.wheel.update()

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Видео для оверлея", "",
                                             "Видео (*.mp4 *.mkv *.mov *.webm);;Все файлы (*)")
        if path:
            self.video_path = Path(path)
            self.video_label.setText(self.video_path.name)
            self.video_label.setToolTip(str(self.video_path))

    def stop_effect(self) -> None:
        self.cancel.set()
        self.controller.stop_effect()
        self.rotation.stop()
        self.cmd_event.stop()
        self.monitor.stop()
        self.desktop.stop()
        challenge, self.challenge = self.challenge, None
        if challenge:
            challenge.stop()
            challenge.deleteLater()
        cubes, self.cubes = self.cubes, None
        if cubes:
            cubes.stop()
            cubes.deleteLater()
        pong, self.pong = self.pong, None
        if pong:
            pong.stop()
            pong.deleteLater()
        overlay, self.overlay = self.overlay, None
        if overlay:
            overlay.stop()
            overlay.deleteLater()
        self.had_effect = False

    def start_timer(self) -> None:
        if not any(check.isChecked() for check in self.checks):
            self.note_label.setText("Выберите хотя бы один эффект.")
            return
        self.running = True
        self.next_spin = time.monotonic() + INTERVAL
        self.start_button.setText("Перезапустить")
        self.note_label.setText("Таймер запущен. Эффекты действуют независимо от активного окна.")

    def stop_timer(self) -> None:
        self.running = False
        self.spin = None
        self.stop_effect()
        self.start_button.setText("Запустить")
        self.timer_label.setText("02:00")
        self.active_label.setText("Остановлено · ввод восстановлен")
        self.note_label.setText("Все временные эффекты сняты; видео остановлено.")

    def begin_spin(self) -> None:
        if self.spin:
            return
        choices = [i for i, check in enumerate(self.checks) if check.isChecked()]
        if not choices:
            self.note_label.setText("Выберите хотя бы один эффект.")
            return
        self.stop_effect()
        selected = random.choice(choices)
        step = 360 / len(EFFECTS)
        desired = 90 - (selected + 0.5) * step
        final = self.wheel.angle + 4 * 360 + (desired - self.wheel.angle) % 360
        self.spin = (selected, time.monotonic(), self.wheel.angle, final)
        self.active_label.setText("Колесо вращается…")
        self.note_label.setText("Демо-вращение" if self.demo_check.isChecked() else
                               "Сейчас будет применён выбранный глобальный эффект.")

    def effect_duration(self, kind):
        return next(e.seconds for e in EFFECTS if e.kind==kind)

    def apply_selected(self, index: int, manual: bool = False) -> None:
        effect = EFFECTS[index]
        seconds = self.effect_duration(effect.kind)
        if not manual and not self.checks[index].isChecked():
            self.active_label.setText("Выбранный эффект отключён")
            return
        self.effect_title = effect.title
        self.active_label.setText(effect.title)
        if self.demo_check.isChecked():
            self.note_label.setText(f"Демо: {effect.title}, {seconds} секунд. Действие не выполнялось.")
            return
        if effect.kind in ("chess", "ai"):
            self.show_challenge(effect.kind)
            return
        if effect.kind == "video":
            self.show_video(auto_win=True)
            return
        if effect.kind == "reverse":
            try:
                self.rotation.start(seconds)
                self.note_label.setText(f"Переворот монитора на 180°: {seconds} с. F12 — выход.")
            except Exception as exc:
                self.note_label.setText(f"Переворот не запущен: {exc}")
            return
        if effect.kind == "cmd":
            try:
                directory = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
                self.cmd_event.start(directory, seconds)
                self.note_label.setText(f"Консоль: color 2 и dir /s в папке программы. Закрытие через {seconds} с; F12 — выход.")
            except Exception as exc:
                self.note_label.setText(f"Консоль не запущена: {exc}")
            return
        if effect.kind == "monitor":
            try:
                self.cancel = threading.Event()
                self.controller.lock_for_monitor(self.cancel, seconds)
                self.monitor.start(seconds)
                self.note_label.setText(f"Монитор: выключение на {seconds} с с блоком ввода. F12 — включить и выйти.")
            except Exception as exc:
                self.controller.stop_effect()
                self.note_label.setText(f"Выключение монитора не запущено: {exc}")
            return
        if effect.kind == "desktop":
            try:
                self.desktop.start()
                self.note_label.setText("Переход на рабочий стол 2; если его нет, он будет создан.")
            except Exception as exc:
                self.note_label.setText(f"Рабочий стол: {exc}")
            return
        if effect.kind == "cubes":
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            cubes = RedCubes(screen, seconds)
            self.cubes = cubes
            cubes.finished.connect(lambda: self.cubes_finished(cubes))
            cubes.start()
            self.note_label.setText(f"Красные кубы: {seconds} с, максимум 4 куба; каждый живёт до 5 с. F12 — выход.")
            return
        if effect.kind == "pong":
            self.show_pong()
            return
        key = self.tp_key.text().strip().upper()
        if effect.kind == "tp" and (len(key) != 1 or key not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
            self.note_label.setText("Клавиша ТП должна быть одной латинской буквой или цифрой.")
            return
        self.cancel = threading.Event()
        if effect.kind == "buy":
            try:
                x, y = (int(part.strip()) for part in self.shop_xy.text().split(","))
            except ValueError:
                self.note_label.setText("Укажите координаты ТП в формате x, y или запомните позицию кнопкой.")
                return
            self.controller.shop_position = (x, y)
            self.controller.shop_key = self.shop_key.text()
        owner = self.cancel
        self.note_label.setText(f"Запуск: {effect.title}")

        def work() -> None:
            try:
                result = self.controller.activate(effect.kind, key, owner, duration=seconds or None)
                self.messages.put((owner, result))
            except Exception as exc:
                self.messages.put((owner, f"Эффект отменён: {exc}"))

        threading.Thread(target=work, daemon=True, name="RouletteAction").start()

    def show_challenge(self, kind: str) -> None:
        self.cancel = threading.Event()
        owner = self.cancel
        try:
            challenge = (ChessChallenge() if kind == 'chess' else
                         AIChallenge(self.api_key.text(), self.ai_model.currentText().strip()))
            self.challenge = challenge
            challenge.finished.connect(lambda result, reason: self.challenge_finished(challenge, owner, result, reason))
            challenge.start()
            self.note_label.setText('Мини-игра открыта. F12 — аварийный выход; Esc — отмена без закрытия Dota 2.')
        except Exception as exc:
            self.stop_effect()
            self.note_label.setText(f'Не удалось открыть мини-игру: {exc}')

    def challenge_finished(self, challenge, owner, result, reason) -> None:
        if self.challenge is not challenge:
            return
        self.challenge = None
        challenge.deleteLater()
        self.had_effect = False
        self.note_label.setText(reason)
        labels = {'win':'Испытание пройдено', 'loss':'Испытание проиграно',
                  'error':'Испытание отменено из-за ошибки', 'cancel':'Испытание отменено'}
        self.active_label.setText(labels.get(result, 'Испытание завершено'))
        if result != 'loss' or owner.is_set() or self.closed or self.controller.panic.is_set():
            return
        def close_game():
            try:
                result_text = self.controller.activate('kill', cancel=owner)
            except Exception:
                result_text = 'Не удалось закрыть Dota 2. Проверьте права приложения.'
            self.messages.put((owner, reason+' '+result_text))
        threading.Thread(target=close_game, daemon=True, name='ChallengeLoss').start()

    def cubes_finished(self, cubes: RedCubes) -> None:
        if self.cubes is cubes:
            self.cubes = None
            self.had_effect = False
            self.active_label.setText("Красные кубы завершён")
            cubes.deleteLater()

    def show_pong(self) -> None:
        self.cancel = threading.Event()
        owner = self.cancel
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        pong = PongOverlay(lambda: self.controller.pong_keys, screen=screen)
        self.pong = pong
        pong.finished.connect(lambda result: self.pong_finished(pong, owner, result))
        try:
            self.controller.start_pong(owner, 30.0)
            pong.start()
            self.note_label.setText("Пинг-понг: ↑ / ↓, продержитесь 30 секунд. Промах закрывает Dota 2. F12 — выход.")
        except Exception as exc:
            self.stop_effect()
            self.note_label.setText(f"Пинг-понг не запущен: {exc}")

    def pong_finished(self, pong: PongOverlay, owner: threading.Event, result: str) -> None:
        if self.pong is not pong:
            return
        self.pong = None
        self.controller.stop_effect()
        pong.deleteLater()
        self.had_effect = False
        if self.closed or owner.is_set() or self.controller.panic.is_set() or result == "cancel":
            return
        if result == "win":
            self.active_label.setText("Пинг-понг: победа!")
            self.note_label.setText("30 секунд пройдены. Мини-игра закрыта.")
            return
        self.active_label.setText("Пинг-понг: поражение")
        def close_game():
            try:
                message = self.controller.activate("kill", cancel=owner)
            except Exception as exc:
                message = f"Не удалось закрыть Dota 2: {exc}"
            self.messages.put((owner, message))
        threading.Thread(target=close_game, daemon=True, name="PongLoss").start()

    def preview_video(self) -> None:
        self.stop_effect()
        self.effect_title = "Предпросмотр видео"
        self.show_video()

    def show_video(self, auto_win: bool = False) -> None:
        if not self.video_path.is_file():
            self.note_label.setText("Видео не найдено. Нажмите «Выбрать…» и укажите MP4.")
            return
        self.cancel.set()
        previous, self.overlay = self.overlay, None
        if previous:
            previous.stop()
            previous.deleteLater()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        overlay = VideoOverlay(self.video_path, duration=self.effect_duration('video'),
                               volume=self.volume.value() / 100.0, screen=screen)
        self.overlay = overlay
        self.cancel = threading.Event()
        owner = self.cancel
        overlay.started.connect(lambda: self.video_started(overlay, auto_win, owner))
        overlay.finished.connect(lambda: self.video_finished(overlay))
        overlay.failed.connect(lambda text: self.video_failed(overlay, text))
        self.note_label.setText("Загрузка видео со звуком…")
        overlay.start()

    def video_started(self, overlay: VideoOverlay, auto_win: bool = False,
                      owner: threading.Event | None = None) -> None:
        if self.overlay is overlay:
            self.had_effect = True
            self.note_label.setText(f"Видео на {self.effect_duration('video')} с. F12 — выход.")
            if auto_win and owner is not None and not overlay.property("win_requested"):
                overlay.setProperty("win_requested", True)
                def press_win():
                    try:
                        if self.controller.press_windows_once(owner):
                            self.messages.put((owner, "Видео запущено · Win нажата один раз. F12 — выход."))
                    except Exception as exc:
                        self.messages.put((owner, f"Видео запущено; не удалось нажать Win: {exc}"))
                threading.Thread(target=press_win, daemon=True, name="VideoWinKey").start()

    def video_failed(self, overlay: VideoOverlay, text: str) -> None:
        overlay.setProperty("failure_text", text)
        self.note_label.setText(f"Ошибка видео: {text}")

    def video_finished(self, overlay: VideoOverlay) -> None:
        if self.overlay is overlay:
            self.cancel.set()
            self.overlay = None
            self.had_effect = False
            failure = overlay.property("failure_text")
            self.active_label.setText("Ошибка видео" if failure else "Видео завершено")
            self.note_label.setText(f"Ошибка видео: {failure}" if failure else
                                   "Видеоплеер закрыт, звук остановлен.")
            overlay.deleteLater()

    def tick(self) -> None:
        if self.closed:
            return
        if self.controller.panic.is_set():
            self.close()
            return
        now = time.monotonic()
        for kind, value in self.monitor.poll():
            if kind == "error":
                self.controller.stop_effect()
                self.note_label.setText(f"Монитор: {value}")
            elif kind == "display_off":
                self.note_label.setText("Windows подтвердила отключение дисплея. Возврат по таймеру; F12 — выход.")
            elif kind == "finished":
                self.controller.stop_effect()
                self.active_label.setText("Монитор: команда включения отправлена")
        for kind, value in self.desktop.poll():
            if kind in ("error", "result"):
                self.note_label.setText(f"Рабочий стол: {value}")
        for kind, value in self.cmd_event.poll():
            if kind == "error":
                self.note_label.setText(f"Консоль: {value}")
            elif kind == "finished":
                self.active_label.setText("Консоль закрыта")
        for kind, value in self.rotation.poll():
            if kind == "error":
                self.note_label.setText(f"Переворот: {value}")
            elif kind == "finished":
                self.active_label.setText("Переворот завершён")
        try:
            while True:
                owner, message = self.controller.notifications.get_nowait()
                if not owner.is_set():
                    self.note_label.setText(message)
        except queue.Empty:
            pass
        if self.controller.last_error:
            self.note_label.setText(self.controller.last_error)
            self.controller.last_error = ""
        try:
            while True:
                owner, message = self.messages.get_nowait()
                if not owner.is_set():
                    self.note_label.setText(message)
        except queue.Empty:
            pass
        if self.spin:
            selected, started, initial, final = self.spin
            progress = min(1.0, (now - started) / SPIN_SECONDS)
            self.wheel.angle = initial + (final - initial) * (1 - (1 - progress) ** 3)
            self.wheel.update()
            if progress >= 1:
                self.wheel.angle %= 360
                self.spin = None
                self.apply_selected(selected)
        if self.running:
            left = max(0, math.ceil(self.next_spin - now))
            self.timer_label.setText(f"{left // 60:02d}:{left % 60:02d}")
            if now >= self.next_spin:
                self.next_spin = now + INTERVAL
                self.begin_spin()
        remaining = (self.overlay.remaining() if self.overlay else
                     max(self.controller.remaining(), self.rotation.remaining(), self.cmd_event.remaining(),
                         self.monitor.remaining(), self.pong.remaining() if self.pong else 0))
        remaining = max(remaining, self.cubes.remaining() if self.cubes else 0)
        remaining = max(remaining, self.challenge.remaining() if self.challenge else 0)
        if remaining > 0:
            self.had_effect = True
            self.active_label.setText(f"{self.effect_title}\nОсталось {remaining:.1f} с")
        elif self.had_effect and self.overlay is None:
            self.had_effect = False
            self.active_label.setText("Эффект завершён · ввод восстановлен")
        if now - self.last_focus_check > 0.5:
            self.last_focus_check = now
            admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            self.focus_label.setText("ГЛОБАЛЬНЫЙ РЕЖИМ · " + ("АДМИНИСТРАТОР" if admin else "ОБЫЧНЫЕ ПРАВА"))

    def closeEvent(self, event) -> None:
        if not self.closed:
            self.closed = True
            self.tick_timer.stop()
            self.stop_effect()
            self.controller.close()
            self.api_key.clear()
        event.accept()
        QApplication.instance().quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Запуск в демонстрационном режиме")
    parser.add_argument("--video", type=Path, help="Использовать другое локальное видео")
    parser.add_argument("--preview-video", action="store_true", help="Открыть предпросмотр видео на 30 секунд")
    parser.add_argument("--volume", type=int, default=65, choices=range(0, 101), metavar="0..100",
                        help="Начальная громкость (по умолчанию 65)")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Это приложение требует Windows.")
    if not ctypes.windll.shell32.IsUserAnAdmin():
        # The packaged EXE also has a requireAdministrator manifest. This
        # branch covers launching the Python source. UAC is never bypassed.
        shell = ctypes.windll.shell32
        shell.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                      ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
        shell.ShellExecuteW.restype = ctypes.c_void_p
        arguments = sys.argv[1:] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve()), *sys.argv[1:]]
        result = shell.ShellExecuteW(None, "runas", sys.executable,
                                    subprocess.list2cmdline(arguments), os.getcwd(), 1)
        return 0 if result and result > 32 else 1
    app = QApplication(sys.argv[:1])
    QLocale.setDefault(QLocale('ru_RU'))
    translations = []
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'
    for name in ('qtbase_ru', 'qtmultimedia_ru'):
        translator = QTranslator(app)
        if translator.load(str(resources / (name+'.qm'))):
            app.installTranslator(translator)
            translations.append(translator)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, "Local\\DebuffRouletteAdvancedV2")
    if not mutex:
        QMessageBox.critical(None, "Рулетка дебаффов", "Не удалось создать защиту от повторного запуска.")
        return 1
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        QMessageBox.information(None, "Рулетка дебаффов", "Рулетка уже запущена. Закройте прежний экземпляр перед запуском новой версии.")
        return 0
    app.setApplicationName("Рулетка дебаффов")
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    window = None
    try:
        window = MainWindow(demo=args.demo, video=args.video)

        def report_error(kind, value, traceback) -> None:
            window.stop_timer()
            window.note_label.setText(f"Ошибка; эффекты сняты: {value}")

        sys.excepthook = report_error
        window.volume.setValue(args.volume)
        window.show()
        if args.preview_video:
            QTimer.singleShot(250, window.preview_video)
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, "Рулетка дебаффов", f"Не удалось запустить приложение:\n{exc}")
        return 1
    finally:
        if window and not window.closed:
            window.controller.close()
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())

