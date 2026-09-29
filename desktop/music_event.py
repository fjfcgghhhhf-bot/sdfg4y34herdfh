"""Local music catalog and bounded playback. Paths never come from the server."""
import json
import sys
import time
from pathlib import Path
from PyQt6.QtCore import QObject,QTimer,QUrl,pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer,QAudioOutput

def catalog(custom=None):
    folder=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets'/'music'
    result={}
    try:
        for item in json.loads((folder/'catalog.json').read_text(encoding='utf-8-sig')):
            path=folder/item['file']
            if path.is_file(): result[item['id']]={'title':item['title'],'path':path}
    except (ValueError,OSError,KeyError): pass
    for key,path in (custom or {}).items():
        path=Path(path)
        if path.is_file(): result[key]={'title':path.stem,'path':path}
    return result

class MusicEvent(QObject):
    finished=pyqtSignal(str)
    def __init__(self,path,duration,volume,parent=None):
        super().__init__(parent); self.done=False; self.duration=duration; self.deadline=None
        self.load_deadline=time.monotonic()+10
        self.audio=QAudioOutput(self); self.audio.setVolume(volume)
        self.player=QMediaPlayer(self); self.player.setAudioOutput(self.audio)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.errorOccurred.connect(lambda *_:self.stop('Не удалось воспроизвести музыку.'))
        self.player.playbackStateChanged.connect(self.state_changed)
        self.timer=QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self.tick)
    def start(self): self.timer.start(); self.player.play()
    def set_volume(self,volume):
        if not 0<=volume<=1: raise ValueError('Громкость музыки: 0–100%.')
        self.audio.setVolume(volume)
    def state_changed(self,state):
        if state==QMediaPlayer.PlaybackState.PlayingState and self.deadline is None:
            self.deadline=time.monotonic()+self.duration
    def remaining(self): return max(0,self.deadline-time.monotonic()) if self.deadline else self.duration
    def tick(self):
        if self.deadline and self.remaining()<=0: self.stop('Музыка завершена.')
        elif not self.deadline and time.monotonic()>self.load_deadline: self.stop('Музыка не загрузилась за 10 секунд.')
    def stop(self,reason='Музыка остановлена.'):
        if self.done: return
        self.done=True; self.timer.stop(); self.player.stop(); self.player.setSource(QUrl()); self.finished.emit(reason)
