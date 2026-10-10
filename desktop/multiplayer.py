"""Russian PvP overlays. Server validates all moves, physics and results."""
import time
import chess
from PyQt6.QtCore import Qt,QTimer,QRectF,QEvent
from PyQt6.QtGui import QPainter,QColor,QPen,QFont
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox
from challenge_base import ChallengeWindow
from chess_event import BoardView

class PongView(QWidget):
    def __init__(self):
        super().__init__(); self.snapshot=None; self.received=0; self.side=0
        self.local_y=None; self.direction=0; self.predicted_at=time.monotonic()
        self.playing=False
        self.setMinimumSize(180,100)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def predict(self):
        now=time.monotonic(); dt=min(.1,max(0,now-self.predicted_at)); self.predicted_at=now
        if self.playing and self.local_y is not None:
            self.local_y=min(400,max(50,self.local_y+self.direction*320*dt))
    def set_direction(self,direction):
        self.predict(); self.direction=direction; self.update()
    def receive_snapshot(self,state,elapsed=0):
        self.predict(); self.snapshot=state; self.received=time.monotonic()
        target=min(400,max(50,state['paddles'][self.side]+self.direction*320*min(.25,elapsed/2)))
        if self.local_y is None or abs(target-self.local_y)>120: self.local_y=target
        else: self.local_y+=(target-self.local_y)*(.2 if self.direction else .5)
    def paintEvent(self,event):
        self.predict()
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#0c1220'))
        p.scale(self.width()/800,self.height()/450)
        p.setPen(QPen(QColor('#303e58'),2,Qt.PenStyle.DashLine)); p.drawLine(400,0,400,450)
        if not self.snapshot: return
        state=self.snapshot; dt=min(.12,max(0,time.monotonic()-self.received)) if self.playing else 0
        p.setPen(Qt.PenStyle.NoPen)
        for i,x in enumerate((18,770)):
            p.setBrush(QColor('#b8f36c' if i==self.side else '#c8a6ff'))
            y=self.local_y if i==self.side and self.local_y is not None else state['paddles'][i]
            p.drawRoundedRect(QRectF(x,y-50,12,100),5,5)
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
        self.move_in_flight=False
        self.ready_pending=False
        layout=QVBoxLayout(self); layout.setContentsMargins(8,8,8,8); layout.setSpacing(4)
        self.add_drag_header(layout)
        self.heading=QLabel('  против  '.join(state['players'])); self.heading.setWordWrap(True); layout.addWidget(self.heading)
        self.ready_label=QLabel(); self.ready_label.setWordWrap(True)
        self.ready_label.setStyleSheet('background:#263b31;color:#c5f48e;padding:9px;border-radius:6px;font-weight:600;')
        layout.addWidget(self.ready_label)
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
        # Space/arrow events also reach the game while a child has focus.
        for widget in [self,*self.findChildren(QWidget)]: widget.installEventFilter(self)
        self.network_timer=QTimer(self); self.network_timer.setInterval(70 if self.kind=='pong' else 300)
        self.network_timer.timeout.connect(self.send_state)
        self.timer.setInterval(16)
        self.receive(state)
    def start(self):
        self.open_window(); self.setFocus(); self.timer.start(); self.network_timer.start(); self.send_state()
    def receive(self,state,elapsed=0):
        if self.done or not state or state['id']!=self.match_id: return
        if self.state and state['revision']<self.state['revision']: return
        if self.kind=='pong' and state['status']!='ended' and state['frame']<self.frame: return
        self.state=state; self.frame=state['frame']
        if state['status']=='ended':
            result='loss' if state['loser'] is True else 'win' if state['loser'] is False else 'cancel'
            self.finish(result,state['reason']); return
        waiting=state['status']=='waiting'
        self.ready_label.setVisible(waiting)
        if waiting:
            ready=state.get('ready',[False,False])
            mine=ready[self.side]; other=ready[1-self.side]
            self.ready_label.setText(('Вы готовы. Ждём пробел соперника.' if mine else
                                     'Нажмите ПРОБЕЛ в этом окне, когда будете готовы.')+
                                    f'\nГотовы: {sum(ready)}/2 · Соперник '+('готов' if other else 'ещё не готов'))
        if self.kind=='chess':
            if self.board.fen()!=state['fen']:
                self.board.set_fen(state['fen']); self.view.selected=None; self.view.update()
            if self.scheduled_move and self.scheduled_move[1]!=state['revision']:
                self.scheduled_move=None
            turn='Ваш ход' if self.board.turn==(self.side==0) else 'Ход соперника'
            self.info.setText('Партия начнётся после готовности обоих игроков.' if waiting else
                              ('Вы — белые. ' if self.side==0 else 'Вы — чёрные. ')+turn+'. Без таймера. Поражение — блок ввода на 30 с.')
        else:
            self.view.playing=not waiting
            self.view.receive_snapshot(state['pong'],elapsed)
            self.info.setText('Мяч неподвижен до готовности обоих игроков.' if waiting else
                             ('Ваша ракетка слева' if self.side==0 else 'Ваша ракетка справа')+' · ↑ / ↓ · промах — блок ввода на 30 с')
    def send_state(self,force_input=False):
        # Key edges use their own requests; an outstanding poll cannot eat a short tap.
        if self.done or (self.pending and not force_input) or not self.link.active: return
        if not force_input: self.pending=True
        self.sequence+=1
        payload={'session_id':self.link.session_id,'id':self.match_id,'action':'state',
                 'direction':self.direction,'sequence':self.sequence}
        if self.scheduled_move:
            payload.update(action='move',move=self.scheduled_move[0],revision=self.scheduled_move[1]); self.scheduled_move=None
            self.move_in_flight=True
        def received(data,elapsed):
            if not force_input: self.pending=False
            if payload['action']=='move': self.move_in_flight=False
            if self.done: return
            self.last_reply=time.monotonic(); self.receive(data.get('match'),elapsed)
            if self.scheduled_move: QTimer.singleShot(0,self.send_state)
        def failed(reason):
            if not force_input: self.pending=False
            if payload['action']=='move': self.move_in_flight=False
            if not self.done: self.finish('cancel',reason+' Матч отменён без поражения.')
        self.link.post('/api/client/match',payload,received,failed)
    def mark_ready(self):
        if (self.done or self.ready_pending or not self.link.active or not self.state
                or self.state['status']!='waiting' or self.state.get('ready',[False,False])[self.side]): return
        self.ready_pending=True
        self.ready_label.setText('Отправляем готовность…')
        def received(data,elapsed):
            self.ready_pending=False
            if not self.done:
                self.last_reply=time.monotonic(); self.receive(data.get('match'),elapsed)
        def failed(reason):
            self.ready_pending=False
            if not self.done: self.finish('cancel',reason+' Матч отменён без штрафа.')
        self.link.post('/api/client/match',{'session_id':self.link.session_id,'id':self.match_id,'action':'ready'},received,failed)
    def select_square(self,square):
        if self.done or not self.state or self.state['status']!='active' or self.scheduled_move or self.move_in_flight: return
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
        if (self.done or self.kind!='pong' or not self.state or self.state['status']!='active'
                or key not in (Qt.Key.Key_Up,Qt.Key.Key_Down)): return
        previous=self.direction
        if down: self.keys.add(key)
        else: self.keys.discard(key)
        self.direction=int(Qt.Key.Key_Down in self.keys)-int(Qt.Key.Key_Up in self.keys)
        self.view.set_direction(self.direction)
        if self.direction!=previous: self.send_state(force_input=True)
    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Type.ShortcutOverride,QEvent.Type.KeyPress,QEvent.Type.KeyRelease) and event.key()==Qt.Key.Key_Space:
            if event.type()==QEvent.Type.KeyPress and not event.isAutoRepeat(): self.mark_ready()
            event.accept(); return True
        if self.kind=='pong' and event.type() in (QEvent.Type.ShortcutOverride,QEvent.Type.KeyPress,QEvent.Type.KeyRelease):
            if event.key() in (Qt.Key.Key_Up,Qt.Key.Key_Down):
                if event.type()!=QEvent.Type.ShortcutOverride and not event.isAutoRepeat():
                    self.key_state(event.key(),event.type()==QEvent.Type.KeyPress)
                event.accept(); return True
        return super().eventFilter(watched,event)
    def event(self,event):
        if event.type()==QEvent.Type.WindowDeactivate and getattr(self,'kind',None)=='pong':
            self.keys.clear(); self.key_state(Qt.Key.Key_Up,False)
        return super().event(event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Up,Qt.Key.Key_Down): self.key_state(event.key(),True); event.accept()
        else: super().keyPressEvent(event)
    def keyReleaseEvent(self,event):
        if not event.isAutoRepeat(): self.key_state(event.key(),False)
        super().keyReleaseEvent(event)
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
