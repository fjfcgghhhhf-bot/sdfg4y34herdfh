"""Two real Qt clients, real HTTP, simulated system controller (never kills Dota)."""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'desktop'))
import chess
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from werkzeug.serving import make_server
from integration_client import Quiet,Controller,MemoryStore
from server import create_app
import debuff_roulette_advanced as engine
from remote_window import RemoteWindow

class SpyController(Controller):
    def __init__(self): super().__init__(); self.calls=[]
    def activate(self,*args,**kwargs): self.calls.append((args,kwargs)); return 'Тест: действие записано'

class SilentMusic(QObject):
    """Real client dispatch is tested without sending any audio to the desktop."""
    finished=pyqtSignal(str)
    def __init__(self,path,duration,volume,parent=None):
        super().__init__(parent); self.path=path; self.duration=duration
        self.volumes=[volume]; self.started=False; self.done=False
    def start(self): self.started=True
    def remaining(self): return self.duration if not self.done else 0
    def set_volume(self,volume): self.volumes.append(volume)
    def stop(self):
        self.done=True; self.finished.emit('Тестовая музыка остановлена.')

def main():
    qt=QApplication([]); qt.setStyleSheet(engine.STYLE)
    with tempfile.TemporaryDirectory() as tmp:
        app=create_app({'TESTING':True,'SECRET_KEY':'x'*40,'ADMIN_PASSWORD':'test-password-123456','DATABASE':str(Path(tmp)/'test.sqlite'),'SESSION_COOKIE_SECURE':False})
        admin=app.test_client(); admin.get('/login')
        with admin.session_transaction() as s: csrf=s['csrf']
        admin.post('/login',data={'password':'test-password-123456','csrf':csrf})
        with admin.session_transaction() as s: headers={'X-CSRF-Token':s['csrf']}
        http=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        windows=[]
        def until(condition,timeout=7):
            end=time.monotonic()+timeout
            while not condition() and time.monotonic()<end: qt.processEvents(); time.sleep(.008)
            assert condition(),[w.note_label.text() for w in windows]
        def command(cmd,targets=None):
            r=admin.post('/api/admin/command',headers=headers,json={'targets':targets or [w.config['client_id'] for w in windows],'command':cmd})
            assert r.status_code==200,r.json
            for w in windows: w.link.poll()
        with patch.object(engine,'WindowsController',SpyController), patch('remote_window.MusicEvent',SilentMusic):
            for name in ('Первый','Второй'):
                code=admin.post('/api/admin/invite',headers=headers,json={}).json['code']
                w=RemoteWindow({'username':name,'server':f'http://127.0.0.1:{http.server_port}','code':code},MemoryStore()); windows.append(w); w.show()
            until(lambda:all(w.link.active and not w.link.pending for w in windows))
            command({'action':'event','event':'tp','duration':11},[windows[0].config['client_id']])
            until(lambda:bool(windows[0].controller.calls))
            args,kwargs=windows[0].controller.calls[-1]; assert args[:2]==('tp','T') and kwargs['duration']==11
            windows[0].controller.calls.clear()
            assert 'bearwolf' in windows[0].tracks and windows[0].tracks['bearwolf']['path'].is_file()
            command({'action':'event','event':'music','duration':42,'track':'bearwolf','volume':27},[windows[0].config['client_id']])
            until(lambda:windows[0].music is not None and windows[0].music.started)
            music=windows[0].music
            assert music.duration==42 and music.volumes==[.27]
            video_volume=windows[0].volume.value()
            command({'action':'music_volume','volume':0},[windows[0].config['client_id']])
            until(lambda:music.volumes[-1]==0)
            assert windows[0].music is music and not music.done
            assert windows[0].volume.value()==video_volume and windows[0].remote_settings['music_volume']==0
            command({'action':'music_volume','volume':81},[windows[0].config['client_id']])
            until(lambda:music.volumes[-1]==.81)
            assert windows[0].music is music and not music.done
            command({'action':'event','event':'chess'})
            until(lambda:all(w.match and w.match.state['status']=='active' for w in windows))
            by_side={w.match.side:w for w in windows}
            for side,uci in [(0,'f2f3'),(1,'e7e5'),(0,'g2g4'),(1,'d8h4')]:
                w=by_side[side]; until(lambda:not w.match.pending and w.match.board.turn==(side==0))
                previous=len(app.extensions['matches'].current(w.config['client_id']).board.move_stack)
                w.match.select_square(chess.parse_square(uci[:2])); w.match.select_square(chess.parse_square(uci[2:]))
                until(lambda:len(app.extensions['matches'].current(w.config['client_id']).board.move_stack)>previous if app.extensions['matches'].current(w.config['client_id']) else w.match is None)
            until(lambda:all(w.match is None for w in windows) and len(by_side[0].controller.calls)==1)
            assert by_side[0].controller.calls[0][0]==('kill',) and not by_side[1].controller.calls
            for w in windows: w.controller.calls.clear()
            command({'action':'event','event':'pong'})
            until(lambda:all(w.match and w.match.state['status']=='active' for w in windows))
            first=windows[0]; hub=app.extensions['matches']
            with hub.lock:
                m=hub.current(first.config['client_id']); loser=m.players[0]; m.x=-7; m.vx=-210; m.y=10
            until(lambda:all(w.match is None for w in windows) and sum(len(w.controller.calls) for w in windows)==1)
            assert next(w for w in windows if w.config['client_id']==loser).controller.calls[0][0]==('kill',)
            for w in windows: w.controller.calls.clear()
            command({'action':'event','event':'chess'}); until(lambda:all(w.match is not None for w in windows))
            windows[0].stop_timer(); until(lambda:all(w.match is None for w in windows))
            assert not any(w.controller.calls for w in windows)
            # Immunity is granted only when a spawned target is also hit.
            roll={'result':'immune','special':True,'angle':90.0,'chance':72,'target_half_width':8.0}
            with patch('server.roll_upgrade',return_value=roll) as generator:
                command({'action':'event','event':'upgrader','duration':3,'chance':72},[windows[0].config['client_id']])
                until(lambda:isinstance(windows[0].challenge,__import__('upgrader').Upgrader))
                generator.assert_called_once_with(72)
            windows[0].challenge.grab().save(str(ROOT.parent/'work'/'upgrader-preview.png'))
            until(lambda:windows[0].challenge is None)
            assert windows[0].immune() and not windows[0].controller.calls
            until(lambda:all(not w.link.pending for w in windows))
            command({'action':'start'},[windows[1].config['client_id']]); until(lambda:windows[1].running)
            windows[0].link.disconnect('Тест обрыва'); assert not windows[0].running
            for w in windows: w.close()
        http.shutdown(); http.server_close()
    print('PASS two HTTP/Qt clients: duration/T dispatch, new music track + independent live volume, chess mate loser only, first-miss pong, cancel no penalty, custom upgrader chance + immunity')

if __name__=='__main__': main()
