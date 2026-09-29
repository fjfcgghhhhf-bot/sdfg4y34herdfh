"""Arrow angle and secret appearance are independently chosen by the server."""
import math
import time
from PyQt6.QtCore import Qt,QPointF,QRectF
from PyQt6.QtGui import QPainter,QColor,QPen,QFont,QPolygonF
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton
from challenge_base import ChallengeWindow

class UpgradeWheel(QWidget):
    def __init__(self,special):
        super().__init__(); self.angle=-90; self.special=special; self.setMinimumSize(160,160)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size=min(self.width(),self.height())-16; box=QRectF((self.width()-size)/2,(self.height()-size)/2,size,size)
        center=box.center(); p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#82334b')); p.drawPie(box,0,180*16)
        p.setBrush(QColor('#226b59')); p.drawPie(box,180*16,180*16)
        p.setPen(QColor('#ffffff')); p.setFont(QFont('Segoe UI',10,QFont.Weight.Bold))
        p.drawText(QRectF(box.x(),box.y()+size*.12,size,24),Qt.AlignmentFlag.AlignCenter,'ПОРАЖЕНИЕ')
        if self.special:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#fc65bd')); p.drawPie(box,258*16,24*16)
            p.setPen(QColor('#3c1431')); p.setFont(QFont('Segoe UI',int(size*.1),QFont.Weight.Bold))
            p.drawText(QRectF(center.x()-24,box.y()+size*.82,48,size*.16),Qt.AlignmentFlag.AlignCenter,'?')
        p.setPen(QColor('#ffffff')); p.setFont(QFont('Segoe UI',10,QFont.Weight.Bold))
        p.drawText(QRectF(box.x(),box.y()+size*.68,size,24),Qt.AlignmentFlag.AlignCenter,'ПОБЕДА')
        a=math.radians(self.angle); vector=QPointF(math.cos(a),math.sin(a)); normal=QPointF(-vector.y(),vector.x())
        p.setPen(QPen(QColor('#ffe4a0'),5)); p.drawLine(center,center+vector*(size*.36))
        tip=center+vector*(size*.43); base=center+vector*(size*.31)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#ffe4a0')); p.drawPolygon(QPolygonF([tip,base+normal*10,base-normal*10]))
        p.setBrush(QColor('#eef3ff')); p.drawEllipse(center,7,7)

class Upgrader(ChallengeWindow):
    screen_height_fraction=.5
    def __init__(self,roll,duration):
        super().__init__('Апгрейдер'); self.roll=roll; self.duration=duration; self.started=0
        layout=QVBoxLayout(self); layout.setContentsMargins(10,8,10,8)
        layout.addWidget(QLabel('АПГРЕЙДЕР · верх — проигрыш, низ — победа'))
        self.wheel=UpgradeWheel(roll['special']); layout.addWidget(self.wheel,1)
        label=QLabel('Розовый сектор: попадите стрелкой в «?» → иммунитет на 10 минут.'); label.setWordWrap(True); layout.addWidget(label)
        stop=QPushButton('Отменить · Esc'); stop.clicked.connect(self.stop); layout.addWidget(stop)
    def start(self): self.started=time.monotonic(); self.open_window(); self.start_clock()
    def tick(self):
        if self.done: return
        progress=min(1,(time.monotonic()-self.started)/(self.duration-.7))
        target=5*360+(self.roll['angle']+90)%360
        self.wheel.angle=-90+target*(1-(1-progress)**4); self.wheel.update()
        if self.remaining()<=0:
            result=self.roll['result']
            self.finish(result,{'immune':'Попадание в «?»! Иммунитет от событий на 10 минут.',
                               'win':'Апгрейдер: победа. Dota 2 остаётся открытой.',
                               'loss':'Апгрейдер: стрелка в верхней половине. Поражение.'}[result])
