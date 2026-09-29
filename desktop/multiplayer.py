"""Russian PvP overlays. Server validates all moves, physics and results."""
import time
import chess
from PyQt6.QtCore import Qt,QTimer,QRectF
from PyQt6.QtGui import QPainter,QColor,QPen,QFont
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox
from challenge_base import ChallengeWindow
from chess_event import BoardView

class PongView(QWidget):
    def __init__(self):
        super().__init__(); self.snapshot=None; self.received=0; self.side=0
        self.setMinimumSize(180,100)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#0c1220'))
        p.scale(self.width()/800,self.height()/450)
        p.setPen(QPen(QColor('#303e58'),2,Qt.PenStyle.DashLine)); p.drawLine(400,0,400,450)
        if not self.snapshot: return
        state=self.snapshot; dt=min(.12,max(0,time.monotonic()-self.received))
        p.setPen(Qt.PenStyle.NoPen)
        for i,x in enumerate((18,770)):
            p.setBrush(QColor('#b8f36c' if i==self.side else '#c8a6ff'))
            p.drawRoundedRect(QRectF(x,state['paddles'][i]-50,12,100),5,5)
        p.setBrush(QColor('#ffffff'))
        # Small extrapolation hides polling jitter; authoritative state wins.
        x=min(800,max(0,state['x']+state['vx']*dt)); y=min(442,max(8,state['y']+state['vy']*dt))
        p.drawEllipse(QRectF(x-8,y-8,16,16))

class Multiplayer(ChallengeWindow):
    screen_height_fraction=.5
    def __init__(self,link,state):
        super().__init__('Шахматы · 1 на 1' if state['kind']=='chess' else 'Пинг-понг · 1 на 1')
        self.link=link; self.match_id=state['id']; self.kind=state['kind']; self.side=state['side']
        self.state=None; self.pending=False; self.direction=0; self.sequence=0; self.last_reply=time.monotonic()
        self.scheduled_move=None; self.frame=-1; self.keys=set()
        layout=QVBoxLayout(self); layout.setContentsMargins(8,8,8,8); layout.setSpacing(4)
        self.heading=QLabel('  против  '.join(state['players'])); self.heading.setWordWrap(True); layout.addWidget(self.heading)
        self.info=QLabel(); self.info.setWordWrap(True); layout.addWidget(self.info)
        if self.kind=='chess':
            self.board=chess.Board(); self.view=BoardView(self.board)
            self.view.clicked.connect(self.select_square)
        else:
            self.view=PongView(); self.view.side=self.side
        layout.addWidget(self.view,1)
        row=QHBoxLayout()
        if self.kind=='chess':
            self.promotion=QComboBox()
            for label,piece in [('Ферзь',chess.QUEEN),('Ладья',chess.ROOK),('Слон',chess.BISHOP),('Конь',chess.KNIGHT)]:
                self.promotion.addItem(label,piece)
            row.addWidget(QLabel('Пешка →')); row.addWidget(self.promotion)
        else:
            for text,key in [('↑',Qt.Key.Key_Up),('↓',Qt.Key.Key_Down)]:
                button=QPushButton(text); button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.pressed.connect(lambda k=key:self.key_state(k,True)); button.released.connect(lambda k=key:self.key_state(k,False)); row.addWidget(button)
        stop=QPushButton('Отменить · Esc'); stop.clicked.connect(self.stop); row.addWidget(stop); layout.addLayout(row)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.network_timer=QTimer(self); self.network_timer.setInterval(70 if self.kind=='pong' else 300)
        self.network_timer.timeout.connect(self.send_state)
        self.timer.setInterval(16)
        self.receive(state)
    def start(self):
        self.open_window(); self.setFocus(); self.timer.start(); self.network_timer.start(); self.send_state()
    def receive(self,state):
        if self.done or not state or state['id']!=self.match_id: return
        if self.state and state['revision']<self.state['revision']: return
        if self.kind=='pong' and state['status']!='ended' and state['frame']<self.frame: return
        self.state=state; self.frame=state['frame']
        if state['status']=='ended':
            result='loss' if state['loser'] is True else 'win' if state['loser'] is False else 'cancel'
            self.finish(result,state['reason']); return
        if self.kind=='chess':
            if self.board.fen()!=state['fen']:
                self.board.set_fen(state['fen']); self.view.selected=None; self.view.update()
            turn='Ваш ход' if self.board.turn==(self.side==0) else 'Ход соперника'
            self.info.setText('Подключение соперника…' if state['status']=='waiting' else
                              ('Вы — белые. ' if self.side==0 else 'Вы — чёрные. ')+turn+'. Без таймера.')
        else:
            self.view.snapshot=state['pong']; self.view.received=time.monotonic()
            self.info.setText('Подключение соперника…' if state['status']=='waiting' else
                             ('Ваша ракетка слева' if self.side==0 else 'Ваша ракетка справа')+' · ↑ / ↓ · первый промах — поражение')
    def send_state(self):
        if self.done or self.pending or not self.link.active: return
        self.pending=True; self.sequence+=1
        payload={'session_id':self.link.session_id,'id':self.match_id,'action':'state',
                 'direction':self.direction,'sequence':self.sequence}
        if self.scheduled_move:
            payload.update(action='move',move=self.scheduled_move[0],revision=self.scheduled_move[1]); self.scheduled_move=None
        def received(data,elapsed):
            self.pending=False
            if self.done: return
            self.last_reply=time.monotonic(); self.receive(data.get('match'))
        def failed(reason):
            self.pending=False
            if not self.done: self.finish('cancel',reason+' Матч отменён без поражения.')
        self.link.post('/api/client/match',payload,received,failed)
    def select_square(self,square):
        if self.done or not self.state or self.state['status']!='active' or self.scheduled_move or self.pending: return
        if self.board.turn!=(self.side==0): return
        piece=self.board.piece_at(square)
        if piece and piece.color==self.board.turn:
            self.view.selected=square; self.view.update(); return
        start=self.view.selected
        if start is None: return
        promotion=None; piece=self.board.piece_at(start)
        if piece and piece.piece_type==chess.PAWN and chess.square_rank(square) in (0,7): promotion=self.promotion.currentData()
        move=chess.Move(start,square,promotion=promotion)
        if move in self.board.legal_moves:
            self.scheduled_move=(move.uci(),self.state['revision']); self.send_state()
    def key_state(self,key,down):
        if down: self.keys.add(key)
        else: self.keys.discard(key)
        self.direction=int(Qt.Key.Key_Down in self.keys)-int(Qt.Key.Key_Up in self.keys)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Up,Qt.Key.Key_Down): self.key_state(event.key(),True); event.accept()
        else: super().keyPressEvent(event)
    def keyReleaseEvent(self,event):
        if not event.isAutoRepeat(): self.key_state(event.key(),False)
        super().keyReleaseEvent(event)
    def focusOutEvent(self,event):
        self.keys.clear(); self.direction=0; super().focusOutEvent(event)
    def tick(self):
        if self.done: return
        if not self.link.active or time.monotonic()-self.last_reply>7:
            self.finish('cancel','Связь потеряна. Матч отменён без поражения.'); return
        self.view.update()
    def cleanup(self):
        self.network_timer.stop()
        if self.link.active:
            ended=bool(self.state and self.state['status']=='ended')
            def ack(*_):
                self.link.post('/api/client/match',{'session_id':self.link.session_id,'id':self.match_id,'action':'ack'},lambda *_:None,lambda _:None)
            if ended: ack()
            else: self.link.post('/api/client/match',{'session_id':self.link.session_id,'id':self.match_id,'action':'cancel'},ack,lambda _:None)
