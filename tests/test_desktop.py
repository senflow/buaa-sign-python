from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from buaa_sign.client import CHINA, Schedule, SignResult, ClientError
from buaa_sign.desktop import DesktopService


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'config.json'
        self.path.write_text(json.dumps({'student_number': 'test', 'password': 'secret'}))
        self.client = Mock()
        self.factory = Mock(return_value=self.client)
        self.service = DesktopService(self.path, self.factory)
        now = datetime.now(CHINA)
        self.lesson = Schedule('one', '课程', '教师', '教室', now - timedelta(minutes=5), now + timedelta(hours=1), False)
        self.client.schedules.return_value = [self.lesson]

    def test_startup_and_repeated_snapshot_never_connect(self):
        for _ in range(10):
            self.assertEqual(self.service.handle({'action': 'snapshot'})['courses'], [])
        self.factory.assert_not_called()

    def test_only_manual_refresh_queries_and_reuses_login(self):
        for _ in range(2):
            self.assertTrue(self.service.handle({'action': 'refresh'})['ok'])
        self.assertEqual(self.client.schedules.call_count, 2)
        self.client.login.assert_called_once_with('test', 'secret')
        for _ in range(5): self.service.handle({'action': 'snapshot'})
        self.assertEqual(self.client.schedules.call_count, 2)

    def test_one_click_sign_updates_status_and_repeated_click_does_not_submit(self):
        self.service.handle({'action': 'refresh'})
        self.client.sign.return_value = SignResult(self.lesson, 'success', '已签到')
        before = self.service.updated
        result = self.service.handle({'action': 'sign', 'id': 'one'})
        self.assertTrue(result['courses'][0]['signed'])
        self.assertEqual(self.service.updated, before) # Does not claim whole schedule refreshed.
        self.service.handle({'action': 'sign', 'id': 'one'})
        self.client.sign.assert_called_once_with(self.lesson)
        self.client.schedules.assert_called_once()

    def test_unknown_result_requires_manual_refresh(self):
        self.service.handle({'action': 'refresh'})
        self.client.sign.return_value = SignResult(self.lesson, 'unknown', '待确认')
        result = self.service.handle({'action': 'sign', 'id': 'one'})
        self.assertIsNone(result['courses'][0]['signed'])
        self.service.handle({'action': 'sign', 'id': 'one'})
        self.client.sign.assert_called_once()

    def test_missing_fields_prompt_and_file_credentials_win(self):
        self.path.write_text('{"student_number":"file-user","password":""}')
        reply = self.service.handle({'action':'refresh'})
        self.assertEqual(reply['needs_credentials'], ['password'])
        self.factory.assert_not_called()
        self.service.handle({'action':'refresh', 'student_number':'override', 'password':'entered'})
        self.client.login.assert_called_once_with('file-user', 'entered')
        self.assertNotIn('entered', self.path.read_text())
        self.assertNotIn('entered', json.dumps(self.service.snapshot()))

    def test_account_change_invalidates_courses_before_signing(self):
        self.service.handle({'action':'refresh'})
        self.path.write_text('{"student_number":"other","password":"new"}')
        reply = self.service.handle({'action':'sign', 'id':'one'})
        self.assertFalse(reply['ok'])
        self.assertEqual(reply['courses'], [])
        self.client.sign.assert_not_called()

    def test_refresh_failure_keeps_old_data_and_does_not_retry(self):
        self.service.handle({'action':'refresh'})
        self.client.schedules.side_effect = ClientError('失败')
        reply = self.service.handle({'action':'refresh'})
        self.assertFalse(reply['ok'])
        self.assertEqual(len(reply['courses']), 1)
        self.assertEqual(self.client.schedules.call_count, 2)

    def test_old_date_disables_sign(self):
        self.service.handle({'action':'refresh'})
        self.service.day -= timedelta(days=1)
        self.assertFalse(self.service.handle({'action':'sign', 'id':'one'})['ok'])
        self.client.sign.assert_not_called()

    def test_week_refresh_requests_monday_through_sunday_once(self):
        now = datetime.now(CHINA)
        monday = now.date() - timedelta(days=now.weekday())
        self.client.schedules.side_effect = [[self.lesson], [], [], [], [], [], []]
        reply = self.service.handle({'action': 'refresh_week', 'week_start': (monday + timedelta(days=3)).isoformat()})
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['week_start'], monday.isoformat())
        self.assertEqual([c.args[0] for c in self.client.schedules.call_args_list],
                         [monday + timedelta(days=i) for i in range(7)])
        self.assertEqual(len(reply['courses']), 1)
        for _ in range(3): self.service.handle({'action': 'snapshot'})
        self.assertEqual(self.client.schedules.call_count, 7)

    def test_partial_week_failure_preserves_complete_previous_week(self):
        self.service.handle({'action': 'refresh_week'})
        old_week, old_rows = self.service.week_start, list(self.service.rows)
        self.client.schedules.side_effect = [[], ClientError('network failed')]
        result = self.service.handle({'action': 'refresh_week', 'week_start': (old_week + timedelta(days=7)).isoformat()})
        self.assertFalse(result['ok'])
        self.assertEqual(self.service.week_start, old_week)
        self.assertEqual(self.service.rows, old_rows)

    def test_week_sign_updates_only_target_without_refetching_week(self):
        self.service.handle({'action':'refresh_week'})
        self.client.sign.return_value = SignResult(self.lesson, 'success', '已签到')
        reply = self.service.handle({'action':'sign', 'id':'one'})
        self.assertTrue(reply['ok'])
        self.assertTrue(reply['courses'][0]['signed'])
        self.assertEqual(self.client.schedules.call_count, 7)

    def test_other_week_cannot_sign(self):
        now = datetime.now(CHINA)
        self.service.handle({'action':'refresh_week', 'week_start': (now.date() + timedelta(days=7)).isoformat()})
        self.assertFalse(self.service.handle({'action':'sign', 'id':'one'})['ok'])
        self.client.sign.assert_not_called()

    def test_today_refresh_preserves_other_days_in_loaded_week(self):
        from dataclasses import replace
        self.service.handle({'action': 'refresh_week'})
        tomorrow = replace(self.lesson, id='tomorrow', start=self.lesson.start + timedelta(days=1), end=self.lesson.end + timedelta(days=1))
        self.service.rows.append(tomorrow)
        week = self.service.week_start
        self.client.schedules.reset_mock()
        self.client.schedules.return_value = [replace(self.lesson, signed=True)]
        reply = self.service.handle({'action': 'refresh'})
        self.assertTrue(reply['ok'])
        self.assertEqual(self.service.week_start, week)
        self.assertEqual(len(reply['courses']), 2)
        self.assertTrue(next(s for s in reply['courses'] if s['id'] == 'one')['signed'])
        self.client.schedules.assert_called_once()

    def test_semester_refresh_uses_configured_term_and_replaces_atomically(self):
        self.path.write_text('{"student_number":"test","password":"secret","term":"202620271"}')
        self.client.semester_schedules.return_value = [self.lesson]
        reply = self.service.handle({'action': 'refresh_semester'})
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['term'], '202620271')
        self.client.semester_schedules.assert_called_once_with('202620271')
        old_updated = reply['updated']
        self.client.semester_schedules.side_effect = ClientError('partial failure')
        failed = self.service.handle({'action': 'refresh_semester'})
        self.assertFalse(failed['ok'])
        self.assertEqual(failed['updated'], old_updated)
        self.assertEqual(failed['courses'], reply['courses'])

    def test_semester_snapshot_and_sign_do_not_refetch_semester(self):
        self.client.semester_schedules.return_value = [self.lesson]
        self.service.handle({'action': 'refresh_semester'})
        self.service.handle({'action': 'snapshot'})
        self.client.sign.return_value = SignResult(self.lesson, 'success', '已签到')
        self.assertTrue(self.service.handle({'action': 'sign', 'id': 'one'})['ok'])
        self.client.semester_schedules.assert_called_once()

    def test_restarted_app_reads_semester_cache_and_only_queries_today(self):
        from dataclasses import replace
        tomorrow = replace(self.lesson, id='next-day', start=self.lesson.start + timedelta(days=1), end=self.lesson.end + timedelta(days=1))
        self.client.semester_schedules.return_value = [self.lesson, tomorrow]
        saved = self.service.handle({'action': 'refresh_semester'})
        self.client.reset_mock()
        restarted = DesktopService(self.path, self.factory)
        self.client.schedules.return_value = [replace(self.lesson, signed=True)]
        reply = restarted.handle({'action': 'refresh'})
        self.assertTrue(reply['ok'])
        self.assertEqual(len(reply['courses']), 2)
        self.assertTrue(next(r for r in reply['courses'] if r['id'] == 'one')['signed'])
        self.assertEqual(reply['semester_updated'], saved['semester_updated'])
        self.client.schedules.assert_called_once()
        self.client.semester_schedules.assert_not_called()
        cache = next((self.path.parent / '.cache').glob('*.json'))
        self.assertNotIn('secret', cache.read_text())
        self.assertEqual(cache.stat().st_mode & 0o777, 0o600)

    def test_no_cache_or_corrupt_cache_does_not_query_semester(self):
        self.service.handle({'action': 'refresh'})
        self.client.semester_schedules.assert_not_called()
        directory = self.path.parent / '.cache'
        directory.mkdir(exist_ok=True)
        (directory / f'semester-{self.service.cache_key}.json').write_text('broken JSON')
        restarted = DesktopService(self.path, self.factory)
        reply = restarted.handle({'action': 'refresh'})
        self.assertTrue(reply['ok'])
        self.assertIsNone(reply['term'])
        self.client.semester_schedules.assert_not_called()

    def test_account_cache_is_isolated(self):
        self.client.semester_schedules.return_value = [self.lesson]
        self.service.handle({'action': 'refresh_semester'})
        self.path.write_text('{"student_number":"other","password":"other-password"}')
        self.client.schedules.return_value = []
        restarted = DesktopService(self.path, self.factory)
        reply = restarted.handle({'action': 'refresh'})
        self.assertEqual(reply['courses'], [])
        self.assertIsNone(reply['term'])


if __name__ == '__main__': unittest.main()
