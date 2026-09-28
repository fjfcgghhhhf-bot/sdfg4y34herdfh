"""Реальный HTTP + Qt, фиксированное демо; системные действия заменены."""
import os
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'desktop'))
from werkzeug.serving import make_server,WSGIRequestHandler
from PyQt6.QtWidgets import QApplication
from server import create_app
from protocol import EVENTS,DEFAULT_SETTINGS
from client_store import Store
import debuff_roulette_advanced as engine
from remote_window import RemoteWindow
from remote_ai import RemoteAIChallenge

class Quiet(WSGIRequestHandler):
    def log_request(self,*_): pass
class Controller:
    def __init__(self): self.panic=threading.Event(); self.notifications=queue.SimpleQueue(); self.last_error=''; self.stops=0
    def start(self): pass
    def close(self): pass
    def stop_effect(self): self.stops+=1
    def remaining(self): return 0
    def activate(self,*_,**__): raise AssertionError('Системное действие запрещено в тесте')
class MemoryStore:
    def save(self,value): self.value=dict(value)

def main():
    qt=QApplication([]); qt.setStyleSheet(engine.STYLE)
    with tempfile.TemporaryDirectory() as tmp:
        app=create_app({'TESTING':True,'SECRET_KEY':'x'*40,'ADMIN_PASSWORD':'test-password-123456','DATABASE':str(Path(tmp)/'db.sqlite'),'SESSION_COOKIE_SECURE':False})
        admin=app.test_client(); admin.get('/login')
        with admin.session_transaction() as s: csrf=s['csrf']
        admin.post('/login',data={'password':'test-password-123456','csrf':csrf})
        with admin.session_transaction() as s: headers={'X-CSRF-Token':s['csrf']}
        invite=admin.post('/api/admin/invite',headers=headers,json={}).json['code']
        http=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start()
        with patch.object(engine,'WindowsController',Controller):
            w=RemoteWindow({'username':'Тестовый клиент','server':f'http://127.0.0.1:{http.server_port}','code':invite},MemoryStore(),demo=True)
            w.show()
            def until(condition,timeout=5):
                end=time.monotonic()+timeout
                while not condition() and time.monotonic()<end: qt.processEvents(); time.sleep(.01)
                assert condition(),w.note_label.text()
            until(lambda:w.link.active)
            cid=w.config['client_id']
            def send(cmd):
                response=admin.post('/api/admin/command',headers=headers,json={'targets':[cid],'command':cmd})
                assert response.status_code==200,response.json
                w.link.poll()
            send({'action':'start'}); until(lambda:w.running)
            send({'action':'stop'}); until(lambda:not w.running)
            for event in EVENTS:
                w.note_label.setText('Ожидание теста')
                send({'action':'event','event':event[0]})
                until(lambda:w.note_label.text().startswith('Демо:'))
            cfg={**DEFAULT_SETTINGS,'volume':25,'tp_key':'G','demo':False}
            send({'action':'settings','settings':cfg}); until(lambda:w.volume.value()==25)
            assert w.demo_check.isChecked(), 'Сайт не может отключить локальный --demo'
            send({'action':'spin'}); until(lambda:w.spin is not None)
            w.grab().save(str(ROOT.parent/'work'/'remote-client.png'))
            reply={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
                'reply_ru':'Убедите меня оставить игру открытой.','close_confidence':80})}}]}
            with patch('ai_gateway.respond',return_value=reply):
                chat=RemoteAIChallenge(w.link,'gemini'); chat.start()
                until(lambda:chat.score is not None)
                assert chat.score==80 and chat.deadline is not None
                chat.stop(); assert chat.done
                chat.deleteLater()
            # Dropping the link cancels an in-progress spin and timer.
            send({'action':'start'}); until(lambda:w.running)
            http.shutdown()
            until(lambda:not w.link.active,timeout=10)
            assert not w.running and w.spin is None and w.controller.stops>0
            w.close(); qt.processEvents()
        # DPAPI round trip; no token plaintext in the persisted file.
        store=Store(Path(tmp)/'client.json'); secret='local-test-token'
        store.save({'server':'https://example.invalid','username':'Тест','token':secret})
        assert secret not in store.path.read_text() and store.load()['token']==secret
        http.server_close()
    print('PASS HTTP enrollment, 18 events, start/stop, settings, forced demo, AI proxy reply, disconnect cleanup, DPAPI')

if __name__=='__main__': main()
