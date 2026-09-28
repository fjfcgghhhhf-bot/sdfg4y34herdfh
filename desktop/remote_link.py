"""Асинхронный HTTPS polling; команды устаревают и не повторяются."""
import json
import time
from PyQt6.QtCore import QObject, QTimer, QUrl, QByteArray, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

class RemoteLink(QObject):
    connected=pyqtSignal()
    disconnected=pyqtSignal(str)
    command_received=pyqtSignal(dict)
    enrolled=pyqtSignal(dict)
    def __init__(self,config,snapshot,parent=None):
        super().__init__(parent); self.config=config; self.snapshot=snapshot
        self.network=QNetworkAccessManager(self); self.session_id=''; self.generation=0
        self.active=False; self.pending=False; self.last_ok=0; self.acks=[]; self.seen=set()
        self.poll_timer=QTimer(self); self.poll_timer.setInterval(1000); self.poll_timer.timeout.connect(self.poll)
        self.guard=QTimer(self); self.guard.setInterval(250); self.guard.timeout.connect(self.watchdog); self.guard.start()
    def post(self,path,body,callback):
        generation=self.generation; sent=time.monotonic()
        req=QNetworkRequest(QUrl(self.config['server']+path)); req.setTransferTimeout(6000)
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        if self.config.get('token'): req.setRawHeader(b'Authorization',('Bearer '+self.config['token']).encode())
        reply=self.network.post(req,QByteArray(json.dumps(body,ensure_ascii=False).encode()))
        def done():
            raw=bytes(reply.readAll()); code=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            failed=reply.error()!=QNetworkReply.NetworkError.NoError; reply.deleteLater()
            if generation!=self.generation: return
            try:
                if len(raw)>131072: raise ValueError('Ответ сервера слишком большой.')
                data=json.loads(raw) if raw else {}
                if failed or code!=200: raise ValueError(data.get('error','Нет связи с сервером.'))
                callback(data,time.monotonic()-sent)
            except Exception as error:
                self.disconnect(str(error) if isinstance(error,ValueError) else 'Ошибка связи. Подключитесь снова.')
        reply.finished.connect(done)
    def connect_server(self):
        self.generation+=1; self.active=False; self.pending=False; self.acks=[]; self.seen.clear()
        if not self.config.get('token'):
            self.post('/api/enroll',{'username':self.config['username'],'code':self.config.get('code','')},self.on_enroll)
        else: self.post('/api/client/session',{},self.on_session)
    def on_enroll(self,data,elapsed):
        self.config.update(token=data['token'],client_id=data['client_id'],username=data['username'])
        self.config.pop('code',None); self.enrolled.emit(self.config)
        self.post('/api/client/session',{},self.on_session)
    def on_session(self,data,elapsed):
        self.session_id=data['session_id']; self.active=True; self.last_ok=time.monotonic()
        self.connected.emit(); self.poll_timer.start(); self.poll()
    def poll(self):
        if not self.active or self.pending: return
        self.pending=True; sent_acks=list(self.acks)
        def receive(data,elapsed):
            self.pending=False
            if data.get('session_id')!=self.session_id: raise ValueError('Сеанс изменился.')
            self.last_ok=time.monotonic()
            self.acks=[x for x in self.acks if x not in sent_acks]
            for item in data.get('commands',[]):
                cid=item['id']
                if cid in self.seen: continue
                self.seen.add(cid)
                if len(self.seen)>2000: self.disconnect('Переподключитесь для нового сеанса.'); return
                if elapsed>=min(8,float(item['ttl'])):
                    self.ack(cid,False,'Команда устарела при доставке.'); continue
                self.command_received.emit(item)
        self.post('/api/client/poll',{'session_id':self.session_id,'status':self.snapshot(),'acks':sent_acks},receive)
    def ack(self,cid,ok,detail):
        self.acks.append({'id':cid,'status':'accepted' if ok else 'rejected','detail':str(detail)[:300]})
    def watchdog(self):
        if self.active and time.monotonic()-self.last_ok>=8:
            self.disconnect('Связь потеряна. Эффекты сняты. Нажмите «Подключиться».')
    def disconnect(self,reason='Удалённое управление отключено.'):
        self.generation+=1; self.active=False; self.pending=False; self.session_id=''; self.poll_timer.stop()
        self.disconnected.emit(reason)
