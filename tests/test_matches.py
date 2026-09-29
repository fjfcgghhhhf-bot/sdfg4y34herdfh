import time
import unittest
from unittest.mock import patch
import chess
from matches import MatchHub

class MatchTests(unittest.TestCase):
    def start(self,kind):
        hub=MatchHub(); mid=hub.create(kind,('a','b'),('Первый','Второй'))
        hub.action('a',mid,{}); hub.action('b',mid,{})
        self.assertEqual(hub.view('a')['status'],'active')
        return hub,mid,hub.current('a')
    def test_chess_mate_only_loser_and_revision(self):
        hub,mid,m=self.start('chess')
        with self.assertRaises(ValueError): hub.action('b',mid,{'action':'move','move':'e7e5','revision':m.revision})
        for cid,move in [('a','f2f3'),('b','e7e5'),('a','g2g4'),('b','d8h4')]:
            revision=m.revision
            hub.action(cid,mid,{'action':'move','move':move,'revision':revision})
            # Retrying a stale request cannot produce a second move.
            hub.action(cid,mid,{'action':'move','move':move,'revision':revision})
        self.assertTrue(hub.view('a')['loser']); self.assertFalse(hub.view('b')['loser'])
        self.assertEqual(len(m.board.move_stack),4)
        hub.ack('a',mid); self.assertIsNone(hub.view('a')); self.assertIsNotNone(hub.view('b'))
    def test_draw_and_cancel_have_no_loser(self):
        hub,mid,m=self.start('chess')
        # White captures the last rook, leaving only two kings.
        m.board=chess.Board('k7/8/8/8/8/8/8/6rK w - - 0 1')
        hub.action('a',mid,{'action':'move','move':'h1g1','revision':m.revision})
        self.assertEqual(m.status,'ended'); self.assertIsNone(m.loser)
        for cid in ('a','b'): self.assertIsNone(hub.view(cid)['loser'])
        hub,mid,m=self.start('pong'); hub.action('a',mid,{'action':'cancel'})
        self.assertIsNone(m.loser); self.assertEqual(m.status,'ended')
    def test_pong_first_miss(self):
        hub,mid,m=self.start('pong'); m.x=-7; m.y=10; m.vx=-210; m.last=time.monotonic()-.02
        hub.action('b',mid,{'direction':0,'sequence':1})
        self.assertEqual(m.status,'ended'); self.assertEqual(m.loser,'a')
        self.assertFalse(hub.view('b')['loser']); self.assertTrue(hub.view('a')['loser'])
    def test_disconnect_and_server_stall_cancel(self):
        hub,mid,m=self.start('chess'); m.seen['a']=time.monotonic()-9
        self.assertEqual(hub.view('b')['status'],'ended'); self.assertIsNone(m.loser)
        hub,mid,m=self.start('pong'); m.last=time.monotonic()-2
        hub.action('b',mid,{}); self.assertEqual(m.status,'ended'); self.assertIsNone(m.loser)
    def test_membership_pairing_and_no_match_timer(self):
        hub,mid,m=self.start('chess')
        with self.assertRaises(ValueError): hub.action('stranger',mid,{})
        with self.assertRaises(ValueError): hub.create('chess',('a','c'),('А','В'))
        m.created-=3600
        self.assertEqual(hub.view('a')['status'],'active')

if __name__=='__main__': unittest.main()
