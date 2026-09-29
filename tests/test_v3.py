"""Сквозная проверка новых настроек без выполнения системных эффектов."""
import time
import unittest
from unittest.mock import patch

import test_server
from protocol import DEFAULT_SETTINGS, command, settings


class Version3Tests(unittest.TestCase):
    setUp = test_server.ServerTests.setUp
    tearDown = test_server.ServerTests.tearDown
    post = test_server.ServerTests.post
    enroll = test_server.ServerTests.enroll
    poll = test_server.ServerTests.poll
    sql = test_server.ServerTests.sql

    def test_percent_settings_accept_bounds_and_reject_nonintegers(self):
        self.assertEqual(settings({})['upgrader_chance'], 50)
        self.assertEqual(settings({})['music_volume'], 65)
        for field in ('upgrader_chance', 'music_volume'):
            for value in (0, 1, 30, 50, 99, 100):
                self.assertEqual(settings({field: value})[field], value)
            for value in (True, False, -1, 101, 1.5, float('nan'), float('inf'), '30', None, [], {}):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        settings({field: value})
        # Music and video maintain independent volume settings.
        result = settings({'music_volume': 0, 'volume': 88})
        self.assertEqual((result['music_volume'], result['volume']), (0, 88))
        self.assertEqual(DEFAULT_SETTINGS['music_volume'], 65)

    def test_event_fields_apply_only_to_their_event(self):
        self.assertEqual(command({'action': 'event', 'event': 'upgrader', 'chance': 0})['chance'], 0)
        self.assertEqual(command({'action': 'event', 'event': 'music', 'volume': 100})['volume'], 100)
        self.assertEqual(command({'action': 'music_volume', 'volume': 0}), {'action': 'music_volume', 'volume': 0})
        wrong = [
            {'action': 'event', 'event': 'music', 'chance': 25},
            {'action': 'event', 'event': 'upgrader', 'volume': 25},
            {'action': 'event', 'event': 'video', 'chance': 25},
            {'action': 'event', 'event': 'video', 'volume': 25},
            {'action': 'spin', 'chance': 25},
            {'action': 'stop', 'volume': 25},
            {'action': 'music_volume'},
            {'action': 'music_volume', 'volume': 25, 'event': 'music'},
        ]
        for payload in wrong:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    command(payload)
        for value in (True, -1, 101, 50.0, float('nan'), '50', None):
            for payload in (
                {'action': 'event', 'event': 'upgrader', 'chance': value},
                {'action': 'event', 'event': 'music', 'volume': value},
                {'action': 'music_volume', 'volume': value},
            ):
                with self.subTest(payload=payload):
                    with self.assertRaises(ValueError):
                        command(payload)

    def test_chance_and_music_volume_go_only_to_selected_player(self):
        a, ha, sa, aid, _ = self.enroll('Первый')
        b, hb, sb, bid, _ = self.enroll('Второй')
        payloads = (
            {'action': 'event', 'event': 'upgrader', 'duration': 3, 'chance': 75},
            {'action': 'event', 'event': 'music', 'duration': 45, 'track': 'default', 'volume': 28},
            {'action': 'music_volume', 'volume': 0},
        )
        for payload in payloads:
            response = self.post('/api/admin/command', {'targets': [aid], 'command': payload})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(self.poll(a, ha, sa).json['commands'][0]['command'], payload)
            self.assertEqual(self.poll(b, hb, sb).json['commands'], [])

    def test_live_volume_preserves_match_and_is_available_during_immunity(self):
        a, ha, sa, aid, _ = self.enroll('Левый')
        b, hb, sb, bid, _ = self.enroll('Правый')
        self.post('/api/admin/command', {'targets': [aid, bid], 'command': {'action': 'event', 'event': 'chess'}})
        match_id = self.poll(a, ha, sa).json['match']['id']
        self.sql('UPDATE clients SET immune_until=? WHERE id=?', (time.time() + 600, aid))
        response = self.post('/api/admin/command', {'targets': [aid], 'command': {'action': 'music_volume', 'volume': 12}})
        self.assertEqual(response.status_code, 200, response.json)
        data = self.poll(a, ha, sa).json
        self.assertEqual(data['commands'][0]['command'], {'action': 'music_volume', 'volume': 12})
        self.assertEqual(data['match']['id'], match_id)
        self.assertNotEqual(data['match']['status'], 'ended')

    def test_upgrader_uses_validated_custom_chance(self):
        c, h, session, _, _ = self.enroll('Апгрейдер')
        result = {'result': 'win', 'special': True, 'angle': 130.0, 'chance': 75, 'target_half_width': 8.0}
        with patch('server.roll_upgrade', return_value=result) as roll:
            response = c.post('/api/client/upgrader', headers=h, json={'session_id': session, 'duration': 3, 'chance': 75})
        self.assertEqual(response.status_code, 200, response.json)
        roll.assert_called_once_with(75)
        for key, value in result.items():
            self.assertEqual(response.json[key], value)
        for value in (True, -1, 101, 75.5, '75', None):
            response = c.post('/api/client/upgrader', headers=h, json={'session_id': session, 'duration': 3, 'chance': value})
            self.assertEqual(response.status_code, 400, response.json)


if __name__ == '__main__':
    unittest.main()
