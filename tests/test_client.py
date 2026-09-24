from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest

from buaa_sign.client import CHINA, Client, ClientError, Response, Schedule, Transport, validate_term


def response(data, status=200, headers=None, url="https://sso.buaa.edu.cn/login"):
    return Response(status, url, headers or {}, data if isinstance(data, str) else json.dumps(data))


def row(state="0", **changes):
    return {"id": "s1", "courseName": "测试课程", "classBeginTime": "2026-09-14 10:00:00",
            "classEndTime": "2026-09-14 11:30:00", "signStatus": state, **changes}


def rows(*items):
    return response({"STATUS": "0", "result": list(items)})


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("出现意外的额外请求")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class ClientTests(unittest.TestCase):
    now = datetime(2026, 9, 14, 10, 0, tzinfo=CHINA)

    def client(self, *responses):
        client = Client(FakeTransport(*responses))
        client.user_id, client.session_id = "u1", "session"
        return client

    def schedule(self):
        return Schedule("s1", "测试课程", "", "", self.now, self.now + timedelta(minutes=90), False)

    def test_login_preserves_password_and_follows_relative_redirect(self):
        transport = FakeTransport(
            response("<input value='execution&amp;value' type='hidden' name='execution'>"),
            response("", 302, {"location": "/continue"}),
            response("", 302, {"location": "https://iclass.buaa.edu.cn:8346/?loginName=aBc%2B123&x=1"}),
            response({"STATUS": "0", "result": {"id": "u1"}}),
        )
        client = Client(transport)
        client.login("12345", " password with spaces ")
        self.assertEqual(client.session_id, "aBc+123")
        self.assertEqual(transport.calls[1][2]["form"]["password"], " password with spaces ")
        self.assertEqual(transport.calls[1][2]["form"]["execution"], "execution&value")
        self.assertEqual(transport.calls[2][1], "https://sso.buaa.edu.cn/continue")
        self.assertTrue(transport.calls[3][1].endswith("eschool/app/user/login_buaa.do"))

    def test_login_failure_does_not_retain_authentication(self):
        client = self.client(response('<input name="execution" value="e">'), response("用户名或密码错误"))
        with self.assertRaises(ClientError):
            client.login("student", "secret")
        self.assertEqual(client.user_id, "")

    def test_login_landing_page_enters_my_center(self):
        client = self.client(response('<input name="execution" value="e">'),
                             response("<html>landing page</html>"),
                             response("", 302, {"location": "https://iclass.buaa.edu.cn:8346/?loginName=token"}),
                             response({"STATUS": "0", "result": {"id": "u1"}}))
        client.login("student", "secret")
        self.assertEqual(client.transport.calls[2][2]["params"], {"type": "jumpMyCenter"})
        self.assertEqual(client.session_id, "token")

    def test_login_errors_distinguish_password_and_missing_token(self):
        for body, expected in (("用户名或密码错误", "明确返回"),
                               ('<input name="execution" value="e">', "仍停留在登录表单")):
            client = self.client(response('<input name="execution" value="e">'), response(body))
            with self.assertRaisesRegex(ClientError, expected):
                client.login("student", "secret")
            self.assertEqual(len(client.transport.calls), 2)
        client = self.client(response('<input name="execution" value="e">'),
                             response("landing"), response("no redirect"))
        with self.assertRaisesRegex(ClientError, "这不等于密码错误"):
            client.login("student", "secret")

    def test_untrusted_redirect_is_rejected(self):
        client = self.client(response('<input name="execution" value="e">'),
                             response("", 302, {"location": "https://example.org/?loginName=secret"}))
        with self.assertRaises(ClientError):
            client.login("student", "secret")

    def test_all_courses_preserves_different_ids_with_same_name(self):
        client = self.client(rows(
            {"course_id": "a", "course_name": "数学", "teacher_name": "甲"},
            {"course_id": "b", "course_name": "数学", "teacher_name": "乙"},
            {"course_id": "a", "course_name": "数学", "teacher_name": "甲"}))
        self.assertEqual(len(client.courses("202620271")), 2)
        call = client.transport.calls[0]
        self.assertIn(":8347/", call[1])
        self.assertEqual(call[2]["params"]["xq_code"], "202620271")
        self.assertEqual(call[2]["headers"]["Sessionid"], "session")

    def test_semester_discovers_dates_and_queries_each_once(self):
        client = self.client(
            rows({"course_id": "a", "course_name": "A"}, {"course_id": "b", "course_name": "B"}),
            rows({"courseSchedId": "s1", "classBeginTime": "2026-09-14 10:00:00"}),
            rows({"courseSchedId": "s1", "classBeginTime": "2026-09-14 10:00:00"},
                 {"courseSchedId": "s2", "classBeginTime": "2026-09-14 12:00:00"}),
            rows(row(), row(id="s2", classBeginTime="2026-09-14 12:00:00", classEndTime="2026-09-14 13:00:00")),
        )
        result = client.semester_schedules("202620271")
        self.assertEqual([s.id for s in result], ["s1", "s2"])
        self.assertEqual(len(client.transport.calls), 4)
        self.assertEqual(client.transport.calls[-1][2]["params"]["dateStr"], "20260914")

    def test_semester_missing_schedule_is_failure_not_partial_success(self):
        client = self.client(rows({"course_id": "a", "course_name": "A"}),
                             rows({"courseSchedId": "s1", "classBeginTime": "2026-09-14 10:00:00"}), rows())
        with self.assertRaisesRegex(ClientError, "不完整"):
            client.semester_schedules("202620271")

    def test_empty_semester_catalog_uses_date_range_instead_of_empty_result(self):
        from unittest.mock import Mock
        client = self.client(response({"STATUS": "2"}))
        client._range_schedules = Mock(return_value=[self.schedule()])
        self.assertEqual(len(client.semester_schedules("202620271")), 1)
        client._range_schedules.assert_called_once_with(date(2026, 9, 1), date(2027, 1, 31))

    def test_semester_fallback_respects_explicit_dates(self):
        from unittest.mock import Mock
        client = self.client(response({"STATUS": "2"}))
        client._range_schedules = Mock(return_value=[])
        client.semester_schedules("202620271", start="2026-09-07", end="2027-01-17")
        client._range_schedules.assert_called_once_with(date(2026, 9, 7), date(2027, 1, 17))

    def test_empty_data_and_bad_response_are_distinct(self):
        client = self.client(response({"STATUS": "2"}), response("<html>login</html>"),
                             response({"STATUS": "0"}), response({"STATUS": "9"}))
        self.assertEqual(client.courses("202620271"), [])
        for _ in range(3):
            with self.assertRaises(ClientError):
                client.courses("202620271")

    def test_term_validation(self):
        for term in ("202620271", "202520262"):
            self.assertEqual(validate_term(term), term)
        for term in ("2026", "202620281", "202620273", "", "20262027x"):
            with self.assertRaises(ClientError):
                validate_term(term)

    def test_window_boundaries(self):
        s = self.schedule()
        self.assertFalse(s.eligible(self.now - timedelta(minutes=10, microseconds=1)))
        self.assertTrue(s.eligible(self.now - timedelta(minutes=10)))
        self.assertTrue(s.eligible(s.end - timedelta(microseconds=1)))
        self.assertFalse(s.eligible(s.end))

    def test_candidates_exclude_signed_unknown_and_out_of_window(self):
        client = self.client(rows(row(), row("1", id="signed"), row(None, id="unknown"),
                                 row("0", id="later", classBeginTime="2026-09-14 12:00:00",
                                     classEndTime="2026-09-14 13:00:00")))
        self.assertEqual([s.id for s in client.candidates(self.now)], ["s1"])

    def test_invalid_schedule_fails_closed(self):
        client = self.client(rows(row(classEndTime="bad")))
        with self.assertRaises(ClientError):
            client.candidates(self.now)

    def test_sign_rechecks_status_and_skips_already_signed(self):
        client = self.client(rows(row("1")))
        self.assertEqual(client.sign(self.schedule(), self.now).status, "skipped")
        self.assertEqual(len(client.transport.calls), 1)

    def test_sign_uses_server_timestamp_and_requires_success_marker(self):
        client = self.client(rows(row()), response({"STATUS": "0", "timestamp": 1789351200123}),
                             response({"STATUS": "0", "result": {"stuSignStatus": "1"}}))
        self.assertEqual(client.sign(self.schedule(), self.now).status, "success")
        call = client.transport.calls[-1]
        self.assertTrue(call[1].endswith("/eschool/app/course/stu_scan_sign.action"))
        self.assertEqual(call[2]["params"]["timestamp"], 1789351200123)
        self.assertEqual(call[2]["params"]["id"], "u1")

    def test_unknown_failure_code_is_not_success(self):
        client = self.client(rows(row()), response({"STATUS": "0", "timestamp": 1789351200123}),
                             response({"STATUS": "9"}))
        self.assertEqual(client.sign(self.schedule(), self.now).status, "failed")

    def test_invalid_server_timestamp_prevents_submission(self):
        client = self.client(rows(row()), response({"STATUS": "0", "timestamp": "bad"}))
        with self.assertRaises(ClientError):
            client.sign(self.schedule(), self.now)
        self.assertEqual(len(client.transport.calls), 2)

    def test_missing_success_marker_requires_readback(self):
        client = self.client(rows(row()), response({"STATUS": "0", "timestamp": 1789351200123}),
                             response({"STATUS": "0", "result": {}}), rows(row("0")))
        self.assertEqual(client.sign(self.schedule(), self.now).status, "unknown")

    def test_lost_post_response_is_read_back_never_retried(self):
        client = self.client(rows(row()), response({"STATUS": "0", "timestamp": 1789351200123}),
                             ClientError("timeout"), rows(row("1")))
        self.assertEqual(client.sign(self.schedule(), self.now).status, "success")
        self.assertEqual(sum("stu_scan_sign" in call[1] for call in client.transport.calls), 1)

    def test_midnight_includes_yesterdays_ongoing_class(self):
        client = self.client(rows(), rows(row(classBeginTime="2026-09-13 23:30:00",
                                              classEndTime="2026-09-14 00:30:00")))
        self.assertEqual(len(client.candidates(datetime(2026, 9, 14, 0, 5, tzinfo=CHINA))), 1)


class TransportTests(unittest.TestCase):
    def test_real_http_transport_keeps_cookies_encodes_form_and_does_not_redirect(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Set-Cookie", "test=cookie; Path=/")
                self.send_header("Location", "/next")
                self.end_headers()

            def do_POST(self):
                seen.append((self.path, self.headers.get("Cookie"),
                             self.rfile.read(int(self.headers.get("Content-Length", 0)))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"STATUS":"0"}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            transport = Transport(2)
            url = f"http://127.0.0.1:{server.server_port}/"
            self.assertEqual(transport.request("GET", url).status, 302)
            self.assertEqual(transport.request("POST", url, params={"id": "a+b"},
                                               form={"password": " a&b "}).status, 200)
            self.assertEqual(seen, [("/?id=a%2Bb", "test=cookie", b"password=+a%26b+")])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
