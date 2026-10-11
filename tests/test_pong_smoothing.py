"""Irregular network delivery must not cause render-time teleports."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from matches import MatchHub

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from pong_motion import PongTimeline


class SmoothingTests(unittest.TestCase):
    def test_jittery_packets_render_without_jumps_or_backward_corrections(self):
        timeline=PongTimeline()
        frames=[(i/120,100+100*i/120,225,225,225) for i in range(481)]
        arrival=.15; frame=0; previous=None; distances=[]; gaps=iter([.10,.24,.12,.18,.20]*10)
        for i in range(300):
            now=i/60
            if now>=arrival and frame<len(frames):
                latest=min(480,int(max(0,now-.08)*120))
                timeline.receive(frames[max(0,latest-100):latest+1],now)
                frame=latest; arrival=now+next(gaps)
            pose=timeline.draw(now)
            if pose and previous and now<3.8:
                distances.append(pose[0]-previous[0])
            if pose: previous=pose
        self.assertTrue(distances)
        self.assertGreaterEqual(min(distances),-1e-8)
        self.assertLess(max(distances),2.01)  # 100 units/sec, <=1.18x playback at 60fps.
        self.assertGreater(sum(d>.1 for d in distances)/len(distances),.85)

    def test_out_of_order_packets_do_not_rewind_and_bounce_is_preserved(self):
        timeline=PongTimeline()
        timeline.receive([(1,400,10,200,210),(1.1,410,8,201,211),(1.2,420,18,202,212)],10)
        timeline.receive([(1.05,405,9,200,210)],10.01)
        self.assertEqual(timeline.samples[-1][0],1.2)
        ys=[]
        for i in range(18):
            pose=timeline.draw(10+i/60)
            ys.append(pose[1])
        self.assertGreater(ys[0],min(ys)); self.assertGreater(ys[-1],min(ys))

    def test_server_supplies_substeps_and_acknowledged_input(self):
        with patch('matches.time.monotonic',return_value=100) as clock:
            hub=MatchHub(); mid=hub.create('pong',('a','b'),('А','Б'))
            hub.action('a',mid,{'action':'ready'}); hub.action('b',mid,{'action':'ready'})
            hub.action('a',mid,{'direction':1,'sequence':8})
            clock.return_value=100.3
            state=hub.action('b',mid,{'direction':0,'sequence':2})['pong']
            self.assertGreater(len(state['history']),30)
            self.assertEqual(state['sequence'],[8,2])
            self.assertAlmostEqual(state['history'][-1][0],100.3)
            self.assertAlmostEqual(state['paddles'][0],321)
            self.assertLessEqual(len(state['history']),180)


if __name__=='__main__': unittest.main()
