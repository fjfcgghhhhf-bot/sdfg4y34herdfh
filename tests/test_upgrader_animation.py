"""Фазы апгрейдера: только Qt offscreen и управляемые часы, без действий ОС."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    QApplication = None
else:
    from upgrader import Upgrader


@unittest.skipIf(QApplication is None, 'Для тестов анимации нужен PyQt6.')
class UpgraderAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, result):
        self.now = 100.0
        clock = patch('upgrader.time.monotonic', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        opener = patch('upgrader.ChallengeWindow.open_window')
        opener.start()
        self.addCleanup(opener.stop)
        window = Upgrader({
            'result': result, 'special': result == 'immune',
            'angle': 45.0, 'chance': 50, 'target_half_width': 8,
        }, 3)
        self.addCleanup(window.close)
        self.results = []
        window.finished.connect(lambda result, reason: self.results.append((result, reason)))
        window.start()
        return window

    def tick_at(self, window, elapsed):
        self.now = 100.0 + elapsed
        window.tick()

    def assert_full_sequence(self, result):
        window = self.make_window(result)
        self.assertEqual(window.spin_seconds, 3)
        self.assertAlmostEqual(window.duration, 5.6)
        self.assertAlmostEqual(window.remaining(), 5.6)
        self.assertIsNone(window.wheel.result)
        self.assertEqual(window.wheel.result_progress, 0)

        self.tick_at(window, 2.999)
        self.assertIsNone(window.wheel.result)
        self.assertEqual(self.results, [])

        self.tick_at(window, 3.0)
        self.assertEqual(window.wheel.result, result)
        self.assertAlmostEqual(window.wheel.angle % 360, 45.0)
        self.assertAlmostEqual(window.wheel.result_progress, 0)

        self.tick_at(window, 3.3)
        self.assertGreater(window.wheel.result_progress, 0)
        self.assertLess(window.wheel.result_progress, 1)
        self.assertEqual(self.results, [])

        self.tick_at(window, 3.601)
        self.assertEqual(window.wheel.result_progress, 1)
        self.assertFalse(window.done)
        self.tick_at(window, 5.600)
        self.assertFalse(window.done)  # Полные две секунды после полной заливки.
        self.assertEqual(self.results, [])
        self.tick_at(window, 5.602)
        self.assertTrue(window.done)
        self.assertEqual([item[0] for item in self.results], [result])
        self.assertFalse(window.timer.isActive())
        self.tick_at(window, 20)
        self.assertEqual(len(self.results), 1)

    def test_win_finishes_only_after_fill_and_two_second_hold(self):
        self.assert_full_sequence('win')

    def test_loss_does_not_emit_penalty_until_result_hold_ends(self):
        self.assert_full_sequence('loss')

    def test_immunity_uses_the_same_success_result_sequence(self):
        self.assert_full_sequence('immune')

    def test_delayed_gui_tick_still_holds_completed_fill_for_two_seconds(self):
        window = self.make_window('loss')
        self.tick_at(window, 12)
        self.assertEqual(window.wheel.result, 'loss')
        self.assertEqual(window.wheel.result_progress, 1)
        self.assertFalse(window.done)
        self.assertEqual(self.results, [])
        self.assertAlmostEqual(window.remaining(), 2.0)
        self.tick_at(window, 13.999)
        self.assertFalse(window.done)
        self.assertGreater(window.remaining(), 0)
        self.tick_at(window, 14.001)
        self.assertEqual([item[0] for item in self.results], ['loss'])

    def test_cancel_during_result_fill_never_emits_loss(self):
        window = self.make_window('loss')
        self.tick_at(window, 3.3)
        window.stop()
        self.assertTrue(window.done)
        self.assertEqual([item[0] for item in self.results], ['cancel'])
        self.tick_at(window, 30)
        self.assertEqual([item[0] for item in self.results], ['cancel'])

    def test_cancel_during_result_hold_never_emits_loss(self):
        window = self.make_window('loss')
        self.tick_at(window, 3.601)
        window.stop()
        self.tick_at(window, 30)
        self.assertEqual([item[0] for item in self.results], ['cancel'])


if __name__ == '__main__':
    unittest.main()
