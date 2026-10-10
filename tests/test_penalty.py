"""Thirty-second loss penalty. Controllers are mocks; no actual input is blocked."""
import ctypes
import queue
import sys
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import test_server
from protocol import command,DEFAULT_SETTINGS,PENALTY_SECONDS

class PenaltyServerTests(unittest.TestCase):
    setUp=test_server.ServerTests.setUp
    tearDown=test_server.ServerTests.tearDown
    post=test_server.ServerTests.post
    enroll=test_server.ServerTests.enroll
    poll=test_server.ServerTests.poll
    sql=test_server.ServerTests.sql
    def test_fixed_penalty_duration(self):
        self.assertEqual(command({'action':'event','event':'kill','duration':30})['duration'],30)
        for value in (0,3,29,31,60):
            with self.assertRaises(ValueError): command({'action':'event','event':'kill','duration':value})
        self.assertEqual(DEFAULT_SETTINGS['durations']['kill'],30)
    def test_old_client_is_disconnected_before_commands_or_match_result(self):
        a,ha,sa,aid,_=self.enroll('Старый'); b,hb,sb,bid,_=self.enroll('Новый')
        self.post('/api/admin/command',{'targets':[aid,bid],'command':{'action':'event','event':'chess'}})
        self.post('/api/admin/command',{'targets':[aid],'command':{'action':'event','event':'kill'}})
        r=a.post('/api/client/poll',headers=ha,json={'session_id':sa,'status':{'protocol':4}})
        self.assertEqual(r.status_code,409); self.assertIn('V5',r.json['error'])
        self.assertEqual(self.sql('SELECT session_id FROM clients WHERE id=?',(aid,))[0][0],'')
        self.assertEqual(a.post('/api/client/match',headers=ha,json={'session_id':sa}).status_code,409)
        self.assertEqual(self.sql("SELECT count(*) FROM commands WHERE client_id=? AND status='queued'",(aid,))[0][0],0)

@unittest.skipUnless(sys.platform=='win32','Windows controller')
class PenaltyClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
        from advanced_input import WindowsController,Lease,Target,KeyHookData
        from remote_window import RemoteWindow
        cls.controller_class=WindowsController; cls.lease_class=Lease; cls.target_class=Target
        cls.key_class=KeyHookData; cls.penalty=RemoteWindow.penalty
    def test_legacy_kill_command_only_acquires_bounded_input_lease(self):
        c=self.controller_class.__new__(self.controller_class)
        c.panic=threading.Event(); c._target=Mock(return_value=None); c._call=Mock()
        owner=threading.Event()
        with patch('advanced_input.psutil.process_iter',side_effect=AssertionError('Не перечислять процессы')):
            message=c.activate('kill',cancel=owner,duration=999)
        args=c._call.call_args.args
        self.assertEqual(args[1],'both'); self.assertIs(args[3],owner); self.assertEqual(args[4],30)
        self.assertIn('30',message)
    def test_common_loss_path_blocks_only_loser_and_respects_cancellation(self):
        for result in ('loss','win','cancel','immune','error'):
            for guard in ('none','immune','cancel','closed','panic','demo','offline'):
                with self.subTest(result=result,guard=guard):
                    owner=threading.Event()
                    c=SimpleNamespace(immune=Mock(return_value=guard=='immune'),closed=guard=='closed',
                        controller=SimpleNamespace(panic=threading.Event(),activate=Mock(return_value='Блок ввода')),
                        demo_check=SimpleNamespace(isChecked=Mock(return_value=guard=='demo')),
                        link=SimpleNamespace(active=guard!='offline'),messages=queue.SimpleQueue())
                    if guard=='cancel': owner.set()
                    if guard=='panic': c.controller.panic.set()
                    with patch('remote_window.threading.Thread',side_effect=lambda target,**_:SimpleNamespace(start=target)):
                        type(self).penalty(c,owner,result,'Результат')
                    if result=='loss' and guard=='none':
                        c.controller.activate.assert_called_once_with('both',cancel=owner,duration=30)
                    else: c.controller.activate.assert_not_called()
    def test_f12_precedes_blocking_and_expired_lease_releases(self):
        c=self.controller_class.__new__(self.controller_class)
        c.panic=threading.Event(); c._closing=threading.Event()
        c._release=Mock(side_effect=lambda:setattr(c,'_lease',None))
        c.user=SimpleNamespace(CallNextHookEx=Mock(return_value=0))
        c._lease=self.lease_class('both',self.target_class(0,0,0,'desktop'),time.monotonic()+30,threading.Event())
        key=self.key_class(); key.vkCode=0x41
        self.assertEqual(c._keyboard_callback(0,0x0100,ctypes.addressof(key)),1)
        key.vkCode=0x7B
        self.assertEqual(c._keyboard_callback(0,0x0100,ctypes.addressof(key)),1)
        self.assertTrue(c.panic.is_set()); self.assertIsNone(c._lease)
        c.panic.clear()
        c._lease=self.lease_class('both',self.target_class(0,0,0,'desktop'),time.monotonic()-1,threading.Event())
        self.assertIsNone(c._current()); self.assertIsNone(c._lease)

if __name__=='__main__': unittest.main()
