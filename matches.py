"""Authoritative two-player games. Disconnect/cancel is never a defeat."""
from dataclasses import dataclass,field
import math
import random
import secrets
import threading
import time
import chess

@dataclass
class Match:
    id:str
    kind:str
    players:tuple
    names:tuple
    created:float
    ready:set=field(default_factory=set)
    seen:dict=field(default_factory=dict)
    status:str='waiting'
    loser:str|None=None
    reason:str='Подключение соперника…'
    board:chess.Board=field(default_factory=chess.Board)
    revision:int=0
    ended:float=0.0
    last:float=0.0
    x:float=400.0
    y:float=225.0
    vx:float=210.0
    vy:float=90.0
    paddles:list=field(default_factory=lambda:[225.0,225.0])
    directions:list=field(default_factory=lambda:[0,0])
    input_at:list=field(default_factory=lambda:[0.0,0.0])
    sequence:list=field(default_factory=lambda:[-1,-1])
    def finish(self,reason,loser=None):
        if self.status=='ended': return
        self.status='ended'; self.reason=reason; self.loser=loser; self.ended=time.monotonic(); self.revision+=1

class MatchHub:
    def __init__(self):
        self.lock=threading.RLock(); self.matches={}; self.by_player={}
    def current(self,cid):
        with self.lock:
            self._maintenance()
            mid=self.by_player.get(cid); return self.matches.get(mid)
    def busy(self,cid):
        match=self.current(cid); return bool(match and match.status!='ended')
    def create(self,kind,players,names):
        with self.lock:
            self._maintenance()
            if kind not in ('chess','pong') or len(set(players))!=2: raise ValueError('Для матча нужны два разных игрока.')
            if any(self.busy(cid) for cid in players): raise ValueError('Один из игроков уже участвует в матче.')
            now=time.monotonic(); match=Match(secrets.token_hex(16),kind,tuple(players),tuple(names),now,last=now)
            match.vx=random.choice((-210.0,210.0)); match.vy=random.choice((-90.0,90.0))
            self.matches[match.id]=match
            for cid in players: self.by_player[cid]=match.id
            return match.id
    def cancel(self,cid,reason='Матч отменён. Dota 2 остаётся открытой у обоих.'):
        with self.lock:
            m=self.current(cid)
            if m and m.status!='ended': m.finish(reason)
    def ack(self,cid,mid):
        with self.lock:
            m=self.matches.get(mid)
            if m and cid in m.players and m.status=='ended' and self.by_player.get(cid)==mid:
                self.by_player.pop(cid,None)
    def _maintenance(self):
        now=time.monotonic()
        for m in list(self.matches.values()):
            if m.status=='waiting' and now-m.created>20:
                m.finish('Соперник не открыл матч. Отмена без поражения.')
            elif m.status=='active' and any(now-m.seen.get(cid,m.created)>8 for cid in m.players):
                m.finish('Связь с игроком потеряна. Матч отменён без поражения.')
            if m.status=='ended' and now-m.ended>300:
                self.matches.pop(m.id,None)
                for cid in m.players:
                    if self.by_player.get(cid)==m.id: self.by_player.pop(cid,None)
    def _advance_pong(self,m,now):
        elapsed=max(0,now-m.last); m.last=now
        # A paused/stalled server must not punish either player.
        if elapsed>1:
            m.finish('Пауза связи. Матч отменён без поражения.'); return
        while elapsed>0 and m.status=='active':
            dt=min(elapsed,1/120); elapsed-=dt
            for i in (0,1):
                direction=m.directions[i] if now-m.input_at[i]<.6 else 0
                m.paddles[i]=min(400,max(50,m.paddles[i]+direction*320*dt))
            old=m.x; m.x+=m.vx*dt; m.y+=m.vy*dt
            if m.y<8: m.y=16-m.y; m.vy=abs(m.vy)
            if m.y>442: m.y=884-m.y; m.vy=-abs(m.vy)
            side=0 if m.vx<0 else 1; boundary=38 if side==0 else 762
            crossing=(old>=boundary>=m.x) if side==0 else (old<=boundary<=m.x)
            if crossing and abs(m.y-m.paddles[side])<=58:
                m.x=2*boundary-m.x
                speed=min(460,math.hypot(m.vx,m.vy)+12); angle=(m.y-m.paddles[side])/58*.9
                m.vx=(1 if side==0 else -1)*speed*math.cos(angle); m.vy=speed*math.sin(angle)
            if m.x< -8 or m.x>808:
                m.finish('Пропущен мяч. Матч завершён.',m.players[0 if m.x<0 else 1])
    def view(self,cid):
        with self.lock:
            m=self.current(cid)
            if not m: return None
            i=m.players.index(cid)
            return {'id':m.id,'kind':m.kind,'status':m.status,'reason':m.reason,'revision':m.revision,
                    'players':list(m.names),'side':i,'loser':m.loser==cid if m.loser else None,'frame':m.last,
                    'fen':m.board.fen() if m.kind=='chess' else None,
                    'pong':{'x':m.x,'y':m.y,'vx':m.vx,'vy':m.vy,'paddles':m.paddles.copy()}}
    def action(self,cid,mid,data):
        with self.lock:
            m=self.current(cid)
            if not m or m.id!=mid: raise ValueError('Матч больше не активен.')
            now=time.monotonic(); i=m.players.index(cid); m.seen[cid]=now
            action=data.get('action','state')
            if action=='cancel': self.cancel(cid)
            if m.status=='waiting':
                m.ready.add(cid)
                if len(m.ready)==2:
                    m.status='active'; m.reason='Матч начался'; m.last=now; m.revision+=1
            if m.status=='active':
                if action=='resign': m.finish('Игрок сдался.',cid)
                elif m.kind=='chess' and action=='move':
                    if data.get('revision')!=m.revision: return self.view(cid)
                    if m.board.turn!=(i==0): raise ValueError('Сейчас ход соперника.')
                    try: move=chess.Move.from_uci(str(data.get('move','')))
                    except ValueError: raise ValueError('Неверная запись хода.')
                    if move not in m.board.legal_moves: raise ValueError('Недопустимый ход.')
                    m.board.push(move); m.revision+=1
                    outcome=m.board.outcome(claim_draw=True)
                    if outcome:
                        loser=None if outcome.winner is None else m.players[1 if outcome.winner else 0]
                        m.finish('Ничья.' if loser is None else 'Мат. Партия завершена.',loser)
                elif m.kind=='pong':
                    self._advance_pong(m,now)
                    direction=data.get('direction',0); sequence=data.get('sequence',0)
                    if type(direction) is not int or direction not in (-1,0,1) or type(sequence) is not int:
                        raise ValueError('Неверное управление ракеткой.')
                    if sequence>m.sequence[i]:
                        m.sequence[i]=sequence; m.directions[i]=direction; m.input_at[i]=now
            return self.view(cid)
