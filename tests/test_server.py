import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from server import create_app
from protocol import DEFAULT_SETTINGS,EVENTS,PROTOCOL_VERSION,PVP_EVENTS

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=str(Path(self.tmp.name)/'test.sqlite3')
        self.app=create_app({'TESTING':True,'SECRET_KEY':'a'*40,'ADMIN_PASSWORD':'test-password-123456','DATABASE':self.db,'SESSION_COOKIE_SECURE':False})
        self.admin=self.app.test_client(); self.admin.get('/login')
        with self.admin.session_transaction() as sess: csrf=sess['csrf']
        self.assertEqual(self.admin.post('/login',data={'password':'test-password-123456','csrf':csrf}).status_code,302)
        with self.admin.session_transaction() as sess: self.headers={'X-CSRF-Token':sess['csrf']}
    def tearDown(self): self.tmp.cleanup()
    def post(self,path,data): return self.admin.post(path,json=data,headers=self.headers)
    def enroll(self,name):
        code=self.post('/api/admin/invite',{}).json['code']; c=self.app.test_client()
        r=c.post('/api/enroll',json={'username':name,'code':code}); self.assertEqual(r.status_code,200)
        headers={'Authorization':'Bearer '+r.json['token']}; sid=c.post('/api/client/session',headers=headers,json={}).json['session_id']
        self.poll(c,headers,sid)
        return c,headers,sid,r.json['client_id'],code
    def poll(self,c,h,sid,acks=None):
        return c.post('/api/client/poll',headers=h,json={'session_id':sid,'status':{'settings':DEFAULT_SETTINGS,'protocol':PROTOCOL_VERSION},'acks':acks or []})
    def sql(self,query,args=()):
        db=sqlite3.connect(self.db)
        try:
            rows=db.execute(query,args).fetchall(); db.commit(); return rows
        finally: db.close()
    def test_auth_csrf_and_code_reuse(self):
        outsider=self.app.test_client()
        self.assertEqual(outsider.get('/api/admin/state').status_code,401)
        self.assertEqual(self.admin.post('/api/admin/invite',json={}).status_code,403)
        c,h,sid,cid,code=self.enroll('Игрок')
        self.assertEqual(c.post('/api/enroll',json={'username':'Второй','code':code}).status_code,403)
        self.assertEqual(c.post('/api/admin/invite',headers=h,json={}).status_code,401)
        code=self.post('/api/admin/invite',{}).json['code']
        self.assertEqual(c.post('/api/enroll',json={'username':'игрок','code':code}).status_code,409)
        self.assertEqual(self.admin.post('/api/admin/invite',json={},headers={**self.headers,'Origin':'https://evil.invalid'}).status_code,403)
    def test_private_browser_form_origin_and_csrf(self):
        c=self.app.test_client(); page=c.get('/login')
        self.assertEqual(page.headers['Referrer-Policy'],'same-origin')
        with c.session_transaction() as sess: csrf=sess['csrf']
        # Reproduce the observed browser's Origin:null with its own form token.
        result=c.post('/login',headers={'Origin':'null'},data={'csrf':csrf,'password':'test-password-123456'})
        self.assertEqual(result.status_code,302)
        with c.session_transaction() as sess: token=sess['csrf']
        good={'Origin':'null','X-CSRF-Token':token}
        self.assertEqual(c.post('/api/admin/invite',headers=good,json={}).status_code,200)
        self.assertEqual(c.post('/api/admin/invite',headers={'Origin':'null'},json={}).status_code,403)
        self.assertEqual(c.post('/api/admin/invite',headers={**good,'Origin':'https://evil.invalid'},json={}).status_code,403)
        fresh=self.app.test_client()
        bad=fresh.post('/login',headers={'Origin':'null'},data={'csrf':'!','password':'test-password-123456'})
        self.assertEqual(bad.status_code,403)
        self.assertTrue(bad.content_type.startswith('text/html'))
        with fresh.session_transaction() as sess: self.assertFalse(sess.get('admin',False))
        self.assertEqual(fresh.post('/api/enroll',headers=good,json={'username':'Тест','code':'bad'}).status_code,403)
    def test_all_single_player_events_exact_targets_and_ack(self):
        a,ha,sa,aid,_=self.enroll('Первый'); b,hb,sb,bid,_=self.enroll('Второй')
        for event in EVENTS:
            if event[0] in PVP_EVENTS: continue
            self.assertEqual(self.post('/api/admin/command',{'targets':[aid],'command':{'action':'event','event':event[0]}}).status_code,200)
            items=self.poll(a,ha,sa).json['commands']; self.assertEqual(items[0]['command']['event'],event[0])
            self.assertEqual(self.poll(b,hb,sb).json['commands'],[])
            self.assertEqual(self.poll(a,ha,sa,[{'id':items[0]['id'],'status':'accepted','detail':'Тест'}]).json['commands'],[])
        self.assertEqual(self.admin.get('/api/admin/state').json['commands'][0]['status'],'accepted')
        r=self.post('/api/admin/command',{'targets':'all','command':{'action':'stop'}})
        self.assertEqual(r.json['sent'],2)
        self.assertEqual(self.poll(a,ha,sa).json['commands'][0]['command']['action'],'stop')
        self.assertEqual(self.poll(b,hb,sb).json['commands'][0]['command']['action'],'stop')
    def test_expiry_reconnect_revocation_and_no_replay(self):
        c,h,s,cid,_=self.enroll('Тестовый')
        self.post('/api/admin/command',{'targets':[cid],'command':{'action':'event','event':'kill'}})
        self.sql('UPDATE commands SET expires=0')
        self.assertEqual(self.poll(c,h,s).json['commands'],[])
        self.post('/api/admin/command',{'targets':[cid],'command':{'action':'spin'}})
        new=c.post('/api/client/session',headers=h,json={}).json['session_id']
        self.assertEqual(self.poll(c,h,s).status_code,409)
        self.assertEqual(self.poll(c,h,new).json['commands'],[])
        self.post('/api/admin/revoke',{'client_id':cid})
        self.assertEqual(self.poll(c,h,new).status_code,401)
    def test_queue_replacement_offline_and_allowlist(self):
        c,h,s,cid,_=self.enroll('Тестовый')
        for action in ('start','spin','stop'): self.post('/api/admin/command',{'targets':[cid],'command':{'action':action}})
        self.assertEqual(self.poll(c,h,s).json['commands'][0]['command']['action'],'stop')
        for bad in ({'action':'shell','command':'anything'},{'action':'event','event':'unknown'},{'action':'settings','settings':{'volume':500}}):
            self.assertEqual(self.post('/api/admin/command',{'targets':[cid],'command':bad}).status_code,400)
        self.sql('UPDATE clients SET last_seen=0')
        self.assertEqual(self.post('/api/admin/command',{'targets':'all','command':{'action':'spin'}}).status_code,409)
    def test_ai_proxy_and_secret_absence(self):
        c,h,s,cid,_=self.enroll('ИИ')
        with patch('ai_gateway.respond',return_value={'choices':[]}) as model:
            self.assertEqual(c.post('/api/client/ai',headers=h,json={'session_id':s,'history':[]}).status_code,200)
            model.assert_called_once()
        state=self.admin.get('/api/admin/state').get_data(as_text=True)
        self.assertNotIn(h['Authorization'].removeprefix('Bearer '),state)
        self.assertNotIn('token_hash',state)
    def test_persistence_restarts_discard_actions(self):
        c,h,s,cid,_=self.enroll('Постоянный')
        self.post('/api/admin/command',{'targets':[cid],'command':{'action':'spin'}})
        app=create_app({'TESTING':True,'SECRET_KEY':'a'*40,'ADMIN_PASSWORD':'test-password-123456','DATABASE':self.db,'SESSION_COOKIE_SECURE':False})
        c=app.test_client(); new=c.post('/api/client/session',headers=h,json={}).json['session_id']
        self.assertEqual(self.poll(c,h,new).json['commands'],[])

if __name__=='__main__': unittest.main()
