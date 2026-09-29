import time
from unittest.mock import patch
import unittest
import test_server
from protocol import command,settings,DEFAULT_SETTINGS

class Version2Tests(unittest.TestCase):
    setUp=test_server.ServerTests.setUp
    tearDown=test_server.ServerTests.tearDown
    post=test_server.ServerTests.post
    enroll=test_server.ServerTests.enroll
    poll=test_server.ServerTests.poll
    sql=test_server.ServerTests.sql
    def test_custom_duration_validation_and_delivery(self):
        c,h,s,cid,_=self.enroll('Длительности')
        for value in (True,0,-1,1.2,61):
            with self.assertRaises(ValueError): command({'action':'event','event':'tp','duration':value})
        with self.assertRaises(ValueError): command({'action':'event','event':'chess','duration':60})
        self.assertEqual(settings({'durations':{'video':45}})['durations']['video'],45)
        self.assertEqual(DEFAULT_SETTINGS['durations']['video'],30)
        self.post('/api/admin/command',{'targets':[cid],'command':{'action':'event','event':'music','duration':90,'track':'video'}})
        payload=self.poll(c,h,s).json['commands'][0]['command']; self.assertEqual(payload['duration'],90); self.assertEqual(payload['track'],'video')
    def test_pairing_and_cancellation(self):
        a,ha,sa,aid,_=self.enroll('Левый'); b,hb,sb,bid,_=self.enroll('Правый')
        response=self.post('/api/admin/command',{'targets':[aid],'command':{'action':'event','event':'chess'}})
        self.assertEqual(response.status_code,409)
        response=self.post('/api/admin/command',{'targets':[aid,bid],'command':{'action':'event','event':'chess'}})
        self.assertEqual(response.status_code,200)
        state=self.poll(a,ha,sa).json['match']; self.assertEqual(state['id'],self.poll(b,hb,sb).json['match']['id'])
        self.post('/api/admin/command',{'targets':[aid],'command':{'action':'stop'}})
        self.assertIsNone(self.poll(b,hb,sb).json['match']['loser'])
        self.assertEqual(self.poll(b,hb,sb).json['match']['status'],'ended')
    def test_question_mark_independent_hit_and_immunity(self):
        c,h,s,cid,_=self.enroll('Апгрейдер')
        for expect,special,angle in [('immune',True,90),('win',True,20),('loss',True,220),('win',False,90),('loss',False,270)]:
            self.sql('UPDATE clients SET immune_until=0 WHERE id=?',(cid,))
            roll={'result':expect,'special':special,'angle':angle,'chance':50,'target_half_width':8}
            with patch('server.roll_upgrade',return_value=roll) as generator:
                r=c.post('/api/client/upgrader',headers=h,json={'session_id':s,'duration':7})
            self.assertEqual(r.status_code,200,r.json); self.assertEqual(r.json['result'],expect); self.assertEqual(r.json['special'],special)
            generator.assert_called_once_with(50)
            if expect=='immune':
                self.assertGreater(self.poll(c,h,s).json['immunity'],606)
                for action in ('start','spin','preview_video','event'):
                    payload={'action':action}
                    if action=='event': payload['event']='kill'
                    self.assertEqual(self.post('/api/admin/command',{'targets':[cid],'command':payload}).status_code,409)
                self.assertEqual(self.post('/api/admin/command',{'targets':[cid],'command':{'action':'stop'}}).status_code,200)
    def test_immunity_persists_reconnect_and_excludes_pairing(self):
        a,ha,sa,aid,_=self.enroll('Защищённый'); b,hb,sb,bid,_=self.enroll('Соперник')
        self.sql('UPDATE clients SET immune_until=? WHERE id=?',(time.time()+600,aid))
        sa=a.post('/api/client/session',headers=ha,json={}).json['session_id']
        self.assertGreater(self.poll(a,ha,sa).json['immunity'],590)
        self.assertEqual(b.post('/api/client/match/find',headers=hb,json={'session_id':sb,'kind':'pong'}).status_code,409)
