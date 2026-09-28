"""Мини-игра использует серверный шлюз, не получает ключ провайдера."""
import json
from PyQt6.QtCore import QUrl,QByteArray
from PyQt6.QtNetwork import QNetworkRequest
from ai_event import AIChallenge

class RemoteAIChallenge(AIChallenge):
    def __init__(self,link,provider):
        super().__init__('server-proxy')
        self.link=link; self.provider=provider
        self.state.setText('Чат передаётся серверу и выбранному провайдеру ИИ.')
    def request(self):
        if self.done: return
        if not self.link.active:
            self.finish('error','Нет связи с панелью. Событие отменено.'); return
        if self.deadline is not None:
            self.tick()
            if self.done: return
        self.request_score=self.score
        req=QNetworkRequest(QUrl(self.link.config['server']+'/api/client/ai'))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
        req.setRawHeader(b'Authorization',('Bearer '+self.link.config['token']).encode())
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        req.setTransferTimeout(20000)
        payload={'session_id':self.link.session_id,'provider':self.provider,'history':self.history[-64:],'score':self.request_score}
        self.set_busy(True); self.state.setText('ИИ отвечает… Накал продолжает расти.')
        reply=self.network.post(req,QByteArray(json.dumps(payload,ensure_ascii=False).encode()))
        self.reply=reply; reply.finished.connect(lambda:self.received(reply))
    def received(self,reply):
        super().received(reply)
        if not self.done: self.state.setText('Приведите новый довод! · '+('Gemini' if self.provider=='gemini' else 'Groq'))
