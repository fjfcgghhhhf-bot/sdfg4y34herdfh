"""Real Qt mouse/key events with delayed HTTP callbacks; no system hooks."""
import copy
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import chess
from matches import MatchHub

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
try:
    from PyQt6.QtWidgets import QApplication,QPushButton
except ImportError:
    QApplication=None
else:
    from PyQt6.QtCore import Qt,QPoint,QEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtGui import QKeyEvent
    from multiplayer import Multiplayer

class DelayedLink:
    active=True
    session_id='test-session'
    def __init__(self): self.requests=[]
    def post(self,path,payload,received,failed=None):
        self.requests.append((copy.deepcopy(payload),received,failed))

@unittest.skipIf(QApplication is None,'Нужен PyQt6')
class PvpInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def window(self,kind,side=0):
        hub=MatchHub(); mid=hub.create(kind,('a','b'),('Первый','Второй'))
        hub.action('a',mid,{'action':'ready'}); hub.action('b',mid,{'action':'ready'})
        link=DelayedLink(); window=Multiplayer(link,hub.view(('a','b')[side]))
        window.resize(540,420); window.show(); self.app.processEvents()
        self.addCleanup(window.close)
        return window,link,hub,mid
    def click_square(self,w,square):
        x,y,size=w.view.geometry_board(); sq=chess.parse_square(square)
        point=QPoint(round(x+(chess.square_file(sq)+.5)*size),round(y+(7-chess.square_rank(sq)+.5)*size))
        QTest.mouseClick(w.view,Qt.MouseButton.LeftButton,pos=point)
    def test_chess_clicks_during_slow_poll_are_queued_and_sent_once(self):
        w,link,hub,mid=self.window('chess')
        w.send_state(); self.assertTrue(w.pending)
        self.click_square(w,'e2'); self.assertEqual(w.view.selected,chess.E2)
        self.click_square(w,'e4'); self.assertEqual(w.scheduled_move[0],'e2e4')
        self.assertEqual(len(link.requests),1)
        link.requests[0][1]({'match':hub.view('a')},.45); self.app.processEvents()
        self.assertEqual(len(link.requests),2)
        payload,callback,_=link.requests[-1]
        self.assertEqual(payload['move'],'e2e4'); self.assertTrue(w.move_in_flight)
        callback({'match':hub.action('a',mid,payload)},.45)
        self.assertEqual(w.board.piece_at(chess.E4),chess.Piece(chess.PAWN,chess.WHITE))
        self.assertFalse(w.move_in_flight)
        self.click_square(w,'d2'); self.assertEqual(len(link.requests),2)
    def test_black_can_select_and_move_after_opponent(self):
        w,link,hub,mid=self.window('chess',1)
        hub.action('a',mid,{'action':'move','move':'e2e4','revision':hub.view('a')['revision']})
        w.receive(hub.view('b')); w.send_state()
        self.click_square(w,'e7'); self.click_square(w,'e5')
        self.assertEqual(w.scheduled_move[0],'e7e5')
        link.requests[0][1]({'match':hub.view('b')},.4); self.app.processEvents()
        payload,callback,_=link.requests[-1]
        callback({'match':hub.action('b',mid,payload)},.4)
        self.assertEqual(w.board.piece_at(chess.E5),chess.Piece(chess.PAWN,chess.BLACK))
    def test_pong_short_key_tap_with_child_focus_bypasses_pending_poll(self):
        w,link,_,_=self.window('pong'); w.send_state()
        button=next(b for b in w.findChildren(QPushButton) if 'Отменить' in b.text())
        button.setFocus(); self.app.processEvents()
        QTest.keyPress(button,Qt.Key.Key_Up)
        self.assertEqual(w.direction,-1)
        before=w.view.local_y
        with patch('multiplayer.time.monotonic',return_value=w.view.predicted_at+.05): w.view.predict()
        self.assertLess(w.view.local_y,before)
        QTest.keyRelease(button,Qt.Key.Key_Up)
        self.assertEqual(w.direction,0)
        self.assertEqual([r[0]['direction'] for r in link.requests],[0,-1,0])
        self.assertTrue(w.pending)  # Original state request still outstanding.
    def test_pong_buttons_and_focus_loss_send_stop(self):
        w,link,_,_=self.window('pong',1); w.send_state()
        button=next(b for b in w.findChildren(QPushButton) if b.text()=='↓')
        QTest.mousePress(button,Qt.MouseButton.LeftButton)
        self.assertEqual(w.direction,1)
        QTest.mouseRelease(button,Qt.MouseButton.LeftButton)
        self.assertEqual(w.direction,0)
        QTest.keyPress(w.view,Qt.Key.Key_Down)
        count=len(link.requests)
        self.app.sendEvent(w.view,QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Down,Qt.KeyboardModifier.NoModifier,'',True))
        self.assertEqual(w.direction,1); self.assertEqual(len(link.requests),count)
        self.app.sendEvent(w,QEvent(QEvent.Type.WindowDeactivate))
        self.assertEqual(w.direction,0); self.assertEqual(link.requests[-1][0]['direction'],0)

class PongLatencyTests(unittest.TestCase):
    def test_delayed_tick_integrates_input_before_lease_expires(self):
        hub=MatchHub(); mid=hub.create('pong',('a','b'),('А','Б'))
        hub.action('a',mid,{'action':'ready'}); hub.action('b',mid,{'action':'ready'})
        m=hub.current('a'); now=time.monotonic()
        m.last=now; m.input_at[0]=now; m.directions[0]=-1; m.vx=0; m.vy=0
        hub._advance_pong(m,now+.7)
        self.assertLess(m.paddles[0],60)
        self.assertEqual(m.status,'active')
    def test_out_of_order_state_does_not_undo_new_input(self):
        hub=MatchHub(); mid=hub.create('pong',('a','b'),('А','Б'))
        hub.action('a',mid,{'action':'ready'}); hub.action('b',mid,{'action':'ready'})
        hub.action('a',mid,{'direction':-1,'sequence':3})
        hub.action('a',mid,{'direction':0,'sequence':2})
        self.assertEqual(hub.current('a').directions[0],-1)
        hub.action('a',mid,{'direction':0,'sequence':4})
        self.assertEqual(hub.current('a').directions[0],0)

if __name__=='__main__': unittest.main()
