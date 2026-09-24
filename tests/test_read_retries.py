from datetime import date, datetime
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from buaa_sign.client import CHINA, Client, ClientError, NetworkError, Schedule, Transport
from .test_client import FakeTransport, rows, row, response


class ReadRetryTests(unittest.TestCase):
    def client(self, *responses):
        client = Client(FakeTransport(*responses), network='webvpn')
        client.user_id, client.session_id = 'user', 'session'
        return client

    @patch('buaa_sign.client.sleep')
    def test_transient_daily_failure_recovers_without_reauthentication(self, sleep):
        c = self.client(NetworkError('timeout'), NetworkError('reset'), rows(row()))
        self.assertEqual(len(c.schedules(date(2026, 9, 14))), 1)
        self.assertEqual(len(c.transport.calls), 3)
        self.assertTrue(all(call[0] == 'GET' for call in c.transport.calls))
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

    @patch('buaa_sign.client.sleep')
    def test_exhausted_range_stops_and_reports_date(self, sleep):
        worker = FakeTransport(*[NetworkError('timeout') for _ in range(3)])
        c = self.client()
        c.transport.clone = Mock(return_value=worker)
        with self.assertRaisesRegex(ClientError, '2026-09-14.*3 次.*保留'):
            c._range_schedules(date(2026, 9, 14), date(2026, 9, 14))
        self.assertEqual(len(worker.calls), 3)

    @patch('buaa_sign.client.sleep')
    def test_semester_recovers_catalog_and_daily_queries(self, sleep):
        c = self.client(NetworkError('timeout'), rows())
        worker = FakeTransport(NetworkError('reset'), rows(row()))
        c.transport.clone = Mock(return_value=worker)
        result = c.semester_schedules('202620271', start='2026-09-14', end='2026-09-14')
        self.assertEqual([s.id for s in result], ['s1'])
        self.assertEqual(len(c.transport.calls), 2)
        self.assertEqual(len(worker.calls), 2)

    @patch('buaa_sign.client.sleep')
    def test_session_and_malformed_response_fail_without_retry(self, sleep):
        for result in (ClientError('session expired'), rows({'bad': 'data'})):
            c = self.client(result)
            with self.assertRaises(ClientError):
                c.schedules(date(2026, 9, 14))
            self.assertEqual(len(c.transport.calls), 1)
        sleep.assert_not_called()

    def test_transport_distinguishes_timeout_from_certificate_failure(self):
        for reason, retryable in ((TimeoutError(), True), (ssl.SSLCertVerificationError(), False)):
            transport = Transport()
            transport.opener.open = Mock(side_effect=URLError(reason))
            with self.assertRaises(ClientError) as caught:
                transport.request('GET', 'https://sso.buaa.edu.cn/login')
            self.assertEqual(isinstance(caught.exception, NetworkError), retryable)

    @patch('buaa_sign.client.sleep')
    def test_sign_network_failure_is_not_replayed(self, sleep):
        c = self.client(rows(row()),
                        response({'STATUS': '0', 'timestamp': '1778130000000'}),
                        NetworkError('lost response'), rows(row('1')))
        now = datetime(2026, 9, 14, 10, tzinfo=CHINA)
        item = Schedule('s1', 'test', '', '', now, now.replace(hour=12), False)
        self.assertEqual(c.sign(item, now).status, 'success')
        self.assertEqual(sum('stu_scan_sign.action' in call[1] for call in c.transport.calls), 1)
        sleep.assert_not_called()
