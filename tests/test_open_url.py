"""Открытие сайтов: проверка ссылок, адресатов и клиента без запуска браузера."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_server
from protocol import command, website_url


class WebsiteUrlTests(unittest.TestCase):
    def test_web_urls_preserve_path_query_and_fragment(self):
        for url in ('https://example.com/path?q=1&b=2#here', 'http://localhost:8080/',
                    'https://[::1]:8443/path', 'https://example.com/поиск?q=привет'):
            self.assertEqual(command({'action':'open_url','url':url}), {'action':'open_url','url':url})
        self.assertEqual(website_url(' HTTPS://EXAMPLE.COM/a '), 'https://example.com/a')
        self.assertEqual(website_url('https://пример.рф/путь'), 'https://xn--e1afmkfd.xn--p1ai/путь')

    def test_reject_nonweb_urls_credentials_and_malformed_addresses(self):
        for url in (None, 42, '', 'example.com', 'javascript:alert(1)', 'file:///C:/Windows/notepad.exe',
                    'ms-settings:display', 'steam://run/570', 'data:text/html,test', '//example.com',
                    'https://u:p@example.com', 'https://example.com:99999', 'https://example.com:0',
                    'https://example.com:bad', 'https://a b.com/', 'https://a_b.com/',
                    'https://example.com\\x', 'https://example.com/\nfoo',
                    'https://example.com/%0d%0afoo', 'https://[broken', 'https://'+'a'*2048):
            with self.subTest(url=url), self.assertRaises(ValueError):
                website_url(url)
        for payload in ({'action':'open_url'}, {'action':'open_url','url':'https://example.com','event':'kill'},
                        {'action':'stop','url':'https://example.com'}):
            with self.assertRaises(ValueError): command(payload)


class WebsiteDeliveryTests(unittest.TestCase):
    setUp = test_server.ServerTests.setUp
    tearDown = test_server.ServerTests.tearDown
    post = test_server.ServerTests.post
    enroll = test_server.ServerTests.enroll
    poll = test_server.ServerTests.poll
    sql = test_server.ServerTests.sql

    def test_selected_and_all_delivery_without_repeat(self):
        a,ha,sa,aid,_=self.enroll('Первый'); b,hb,sb,bid,_=self.enroll('Второй')
        payload={'action':'open_url','url':'https://example.com/?a=1&b=2#page'}
        response=self.post('/api/admin/command',{'targets':[aid],'command':payload})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['sent'],1)
        self.assertEqual(self.poll(a,ha,sa).json['commands'][0]['command'],payload)
        self.assertEqual(self.poll(a,ha,sa).json['commands'],[])
        self.assertEqual(self.poll(b,hb,sb).json['commands'],[])
        response=self.post('/api/admin/command',{'targets':'all','command':payload})
        self.assertEqual(response.json['sent'],2)
        self.assertEqual(self.poll(a,ha,sa).json['commands'][0]['command'],payload)
        self.assertEqual(self.poll(b,hb,sb).json['commands'][0]['command'],payload)

    def test_immunity_skips_url_and_v3_keeps_existing_commands(self):
        a,ha,sa,aid,_=self.enroll('Игрок')
        payload={'action':'open_url','url':'https://example.com/'}
        self.sql('UPDATE clients SET immune_until=? WHERE id=?',(time.time()+600,aid))
        self.assertEqual(self.post('/api/admin/command',{'targets':[aid],'command':payload}).status_code,409)
        self.sql('UPDATE clients SET immune_until=0,status=? WHERE id=?',(json.dumps({'protocol':3}),aid))
        r=self.post('/api/admin/command',{'targets':[aid],'command':payload})
        self.assertEqual(r.status_code,409)
        self.assertIn('4',r.json['error'])
        self.assertEqual(self.post('/api/admin/command',{'targets':[aid],'command':{'action':'start'}}).status_code,200)

    def test_invalid_and_unauthorized_commands_are_not_queued(self):
        _,_,_,aid,_=self.enroll('Игрок')
        data={'targets':[aid],'command':{'action':'open_url','url':'https://example.com'}}
        self.assertEqual(self.app.test_client().post('/api/admin/command',json=data).status_code,401)
        self.assertEqual(self.admin.post('/api/admin/command',json=data).status_code,403)
        data['command']['url']='file:///C:/Windows/notepad.exe'
        self.assertEqual(self.post('/api/admin/command',data).status_code,400)
        self.assertEqual(self.sql('SELECT count(*) FROM commands')[0][0],0)


@unittest.skipUnless(sys.platform=='win32','Клиент Windows')
class WebsiteClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
        try:
            from remote_window import RemoteWindow
        except ModuleNotFoundError as exc:
            if exc.name=='PyQt6': raise unittest.SkipTest('Нужен PyQt6')
            raise
        cls.receive=RemoteWindow.receive_command

    def client(self):
        return SimpleNamespace(link=SimpleNamespace(active=True,ack=Mock()),closed=False,
            immune=Mock(return_value=False),demo_check=SimpleNamespace(isChecked=Mock(return_value=False)),
            note_label=SimpleNamespace(setText=Mock()),stop_timer=Mock())

    def dispatch(self,client,url='https://example.com/?a=1&b=2#page'):
        type(self).receive(client,{'id':'one','command':{'action':'open_url','url':url}})

    def test_success_uses_default_browser_and_does_not_stop_events(self):
        client=self.client()
        with patch('remote_window.QDesktopServices.openUrl',return_value=True) as opener:
            self.dispatch(client)
        self.assertEqual(opener.call_args.args[0].toString(),'https://example.com/?a=1&b=2#page')
        self.assertTrue(client.link.ack.call_args.args[1])
        client.stop_timer.assert_not_called()
        self.assertIn('браузеру',client.note_label.setText.call_args.args[0])

    def test_demo_immunity_disconnect_and_bad_urls_do_not_open_browser(self):
        for mode in ('demo','immune','offline','closed','bad_url'):
            with self.subTest(mode=mode):
                client=self.client()
                if mode=='demo': client.demo_check.isChecked.return_value=True
                if mode=='immune': client.immune.return_value=True
                if mode=='offline': client.link.active=False
                if mode=='closed': client.closed=True
                with patch('remote_window.QDesktopServices.openUrl') as opener:
                    self.dispatch(client,'file:///C:/Windows' if mode=='bad_url' else 'https://example.com')
                opener.assert_not_called()
                self.assertEqual(client.link.ack.call_args.args[1],mode=='demo')

    def test_browser_failure_is_reported(self):
        client=self.client()
        with patch('remote_window.QDesktopServices.openUrl',return_value=False):
            self.dispatch(client)
        self.assertFalse(client.link.ack.call_args.args[1])
        self.assertIn('Не удалось открыть браузер',client.link.ack.call_args.args[2])


if __name__=='__main__': unittest.main()
