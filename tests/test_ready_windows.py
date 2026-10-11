"""Readiness handshake and movable overlays, without OS hooks or API calls."""
import copy
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from matches import MatchHub

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
try:
    from PyQt6.QtWidgets import QApplication, QPushButton
except ImportError:
    QApplication = None
else:
    from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
    from PyQt6.QtGui import QMouseEvent, QKeyEvent
    from PyQt6.QtTest import QTest
    from ai_event import AIChallenge
    from multiplayer import Multiplayer


class ReadyServerTests(unittest.TestCase):
    def test_only_two_distinct_ready_commands_start_each_game(self):
        for kind in ('chess', 'pong'):
            with self.subTest(kind=kind):
                hub = MatchHub()
                mid = hub.create(kind, ('a', 'b'), ('А', 'Б'))
                initial = hub.view('a')
                for cid in ('a', 'b'):
                    hub.action(cid, mid, {})
                    hub.action(cid, mid, {'action': 'move', 'move': 'e2e4', 'revision': 0})
                    hub.action(cid, mid, {'direction': 1, 'sequence': 99})
                self.assertEqual(hub.view('a')['ready'], [False, False])
                for _ in range(3):
                    state = hub.action('a', mid, {'action': 'ready'})
                self.assertEqual(state['status'], 'waiting')
                self.assertEqual(state['ready'], [True, False])
                self.assertEqual(state['revision'], 1)
                with self.assertRaises(ValueError):
                    hub.action('outsider', mid, {'action': 'ready'})
                state = hub.action('b', mid, {'action': 'ready'})
                self.assertEqual(state['status'], 'active')
                self.assertEqual(state['ready'], [True, True])
                self.assertEqual(state['fen'], initial['fen'])
                for key in ('x','y','paddles','directions','sequence'):
                    self.assertEqual(state['pong'][key], initial['pong'][key])
                self.assertEqual(hub.current('a').directions, [0, 0])

    def test_wait_has_no_deadline_while_connected_and_disconnect_has_no_loser(self):
        with patch('matches.time.monotonic', return_value=1000) as clock:
            hub = MatchHub()
            mid = hub.create('pong', ('a', 'b'), ('А', 'Б'))
            for instant in range(1000, 1121, 4):
                clock.return_value = instant
                hub.action('a', mid, {})
                state = hub.action('b', mid, {})
                self.assertEqual(state['status'], 'waiting')
                self.assertEqual(state['pong']['x'], 400)
            hub.action('a', mid, {'action': 'ready'})
            clock.return_value = 1130
            state = hub.view('a')
            self.assertEqual(state['status'], 'ended')
            self.assertIsNone(state['loser'])


class DelayedLink:
    active = True
    session_id = 'test'

    def __init__(self):
        self.requests = []

    def post(self, path, payload, received, failed=None):
        self.requests.append((copy.deepcopy(payload), received, failed))


@unittest.skipIf(QApplication is None, 'Нужен PyQt6')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def waiting_window(self, kind):
        hub = MatchHub()
        mid = hub.create(kind, ('a', 'b'), ('А', 'Б'))
        link = DelayedLink()
        window = Multiplayer(link, hub.view('a'))
        window.resize(600, 480)
        window.show()
        self.app.processEvents()
        self.addCleanup(window.close)
        return window, link, hub, mid

    def test_space_on_child_sends_ready_once_despite_pending_poll(self):
        for kind in ('chess', 'pong'):
            with self.subTest(kind=kind):
                w, link, hub, mid = self.waiting_window(kind)
                w.send_state()
                old_state = hub.view('a')
                button = next(b for b in w.findChildren(QPushButton) if 'Отменить' in b.text())
                button.setFocus()
                QTest.keyClick(button, Qt.Key.Key_Space)
                QTest.keyClick(button, Qt.Key.Key_Space)
                self.app.sendEvent(button, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                                   Qt.KeyboardModifier.NoModifier, ' ', True))
                self.assertEqual([r[0]['action'] for r in link.requests], ['state', 'ready'])
                self.assertFalse(w.done)
                payload, callback, _ = link.requests[1]
                callback({'match': hub.action('a', mid, payload)}, .2)
                link.requests[0][1]({'match': old_state}, .4)
                self.assertEqual(w.state['ready'], [True, False])
                self.assertIn('1/2', w.ready_label.text())
                QTest.keyClick(button, Qt.Key.Key_Space)
                self.assertEqual(len(link.requests), 2)
                w.receive(hub.action('b', mid, {'action': 'ready'}))
                self.assertEqual(w.state['status'], 'active')
                self.assertTrue(w.ready_label.isHidden())
                QTest.keyClick(button, Qt.Key.Key_Space)
                self.assertFalse(w.done)  # Space cannot activate the focused Cancel button.
                w.close()

    def test_input_and_prediction_are_frozen_before_ready(self):
        w, link, _, _ = self.waiting_window('pong')
        QTest.keyClick(w.view, Qt.Key.Key_Down)
        self.assertEqual(w.direction, 0)
        self.assertEqual(link.requests, [])
        before = w.view.local_y
        with patch('multiplayer.time.monotonic', return_value=time.monotonic()+1):
            w.view.predict()
        self.assertEqual(w.view.local_y, before)
        self.assertFalse(w.view.playing)
        w, link, _, _ = self.waiting_window('chess')
        w.select_square(12)
        w.select_square(28)
        self.assertIsNone(w.view.selected)
        self.assertEqual(link.requests, [])

    def test_all_three_headers_drag_without_poll_repositioning(self):
        ai = AIChallenge('test-key')  # No start(): never contacts the API.
        ai.show()
        self.addCleanup(ai.close)
        chess, _, hub, _ = self.waiting_window('chess')
        pong, _, pong_hub, _ = self.waiting_window('pong')
        for window in (ai, chess, pong):
            with self.subTest(window=window.windowTitle()):
                window.move(70, 80)
                header = window.drag_header
                local = QPointF(20, 15)
                origin = QPointF(header.mapToGlobal(local.toPoint()))
                delta = QPoint(125, 90)
                for event_type, global_pos, button, buttons in (
                    (QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                    (QEvent.Type.MouseMove, origin+QPointF(delta), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
                    (QEvent.Type.MouseButtonRelease, origin+QPointF(delta), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
                ):
                    self.app.sendEvent(header, QMouseEvent(event_type, local, global_pos, button, buttons,
                                                          Qt.KeyboardModifier.NoModifier))
                self.assertEqual(window.pos(), QPoint(195, 170))
                self.assertIsNone(header.offset)
        chess.receive(hub.view('a'))
        pong.receive(pong_hub.view('a'))
        self.assertEqual(chess.pos(), QPoint(195, 170))
        self.assertEqual(pong.pos(), QPoint(195, 170))


if __name__ == '__main__':
    unittest.main()
