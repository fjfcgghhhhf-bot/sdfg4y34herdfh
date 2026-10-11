"""All keyboard output is mocked; tests never press actual keys."""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,call
from protocol import command,EVENT_IDS

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))


@unittest.skipUnless(sys.platform=='win32','Windows controller')
class KeySequenceTests(unittest.TestCase):
    def controller(self):
        from advanced_input import WindowsController,Target
        c=WindowsController.__new__(WindowsController)
        c.panic=threading.Event(); c._call=Mock(); c._tap_key=Mock()
        c._target=Mock(return_value=None); c._game_window=Mock(return_value=Target(1,2,3,'dota2.exe'))
        c._focus_window=Mock(); c._matches=Mock(return_value=True)
        c.user=SimpleNamespace(GetAsyncKeyState=Mock(return_value=0))
        return c

    def test_registered_event_sends_exact_order_with_released_keys(self):
        self.assertIn('qwedf',EVENT_IDS)
        self.assertEqual(command({'action':'event','event':'qwedf'})['event'],'qwedf')
        with self.assertRaises(ValueError): command({'action':'event','event':'qwedf','duration':5})
        c=self.controller(); cancel=Mock(); cancel.is_set.return_value=False; cancel.wait.return_value=False
        message=c.activate('qwedf',cancel=cancel)
        self.assertEqual(c._tap_key.call_args_list,[call(ord(k)) for k in 'QWEDF'])
        self.assertEqual(cancel.wait.call_args_list,[call(.12)]*4)
        c._focus_window.assert_called_once_with(c._game_window.return_value,cancel)
        self.assertIn('Q → W → E → D → F',message)

    def test_focus_change_cancellation_and_panic_stop_remainder(self):
        for reason in ('focus','cancel','panic','modifier'):
            c=self.controller(); cancel=threading.Event()
            def first(_):
                if reason=='focus': c._matches.return_value=False
                if reason=='cancel': cancel.set()
                if reason=='panic': c.panic.set()
                if reason=='modifier': c.user.GetAsyncKeyState.return_value=0x8000
            c._tap_key.side_effect=first
            with self.subTest(reason=reason),self.assertRaises(RuntimeError):
                c.activate('qwedf',cancel=cancel)
            self.assertEqual(c._tap_key.call_args_list,[call(ord('Q'))])


if __name__=='__main__': unittest.main()
