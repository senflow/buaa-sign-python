from datetime import date, datetime, timedelta
from http.cookiejar import Cookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPSHandler, HTTPCookieProcessor, build_opener
from urllib.response import addinfourl
from email.message import Message
from io import BytesIO
import json
import ssl
import subprocess
import tempfile
import unittest

from buaa_sign import cli
from buaa_sign.client import Client, ClientError, Transport, WebVPNTransport, Schedule, CHINA, NoRedirect
from buaa_sign.desktop import DesktopService
from buaa_sign.webvpn import GATEWAY, TOKENS, gateway_url, original_url
from .test_client import FakeTransport, response, rows, row


FORM = '<form action="/login"><input name="execution" value="e&amp;1"><input name="hidden" value="keep"><input name="password" type="password"></form>'


def web_response(body, status=200, location=None, url=None):
    return response(body, status, {"location": location} if location else {},
                    url or gateway_url("https://sso.buaa.edu.cn/login"))


def cookie():
    return Cookie(0, "wengine_vpn_ticket", "fake-ticket", None, False,
                  "d.buaa.edu.cn", True, False, "/", True, True, None, True,
                  None, None, {}, False)


class WebVPNTests(unittest.TestCase):
    def test_full_gateway_flow_with_real_cookie_processing_and_request_encoding(self):
        case = self
        requests = []

        class GatewayFixture(HTTPSHandler):
            def https_open(self, req):
                requests.append(req)
                case.assertEqual(urlsplit(req.full_url).hostname, "d.buaa.edu.cn")
                logical = urlsplit(original_url(req.full_url))
                headers = Message()
                status, body = 200, {}
                if logical.hostname == "sso.buaa.edu.cn" and req.get_method() == "GET":
                    body = FORM
                    headers["Set-Cookie"] = "flow=one; Path=/; Secure"
                elif logical.hostname == "sso.buaa.edu.cn":
                    case.assertIn("flow=one", req.get_header("Cookie", ""))
                    case.assertEqual(parse_qs(req.data.decode())["password"], [" secret+value "])
                    status = 302
                    headers["Location"] = GATEWAY + "/https/" + TOKENS["d.buaa.edu.cn"] + "/login?cas_login=true&ticket=fixture"
                elif logical.hostname == "d.buaa.edu.cn":
                    if logical.path == "/login":
                        case.assertIn("/https/", req.full_url)
                        status = 302
                        headers["Location"] = "/https/" + TOKENS["d.buaa.edu.cn"] + "/wengine-vpn-token-login?token=fixture"
                    elif logical.path == "/wengine-vpn-token-login":
                        case.assertIn("/https/", req.full_url)
                        status = 302
                        headers["Location"] = "/token-login?token=fixture"
                    elif logical.path == "/token-login":
                        status = 302
                        headers["Location"] = "/"
                        headers["Set-Cookie"] = "vpn=authorized; Path=/; Secure"
                    else:
                        case.assertIn("vpn=authorized", req.get_header("Cookie", ""))
                        body = "portal"
                elif logical.port == 8346:
                    case.assertIn("vpn=authorized", req.get_header("Cookie", ""))
                    status = 302
                    headers["Location"] = "https://iclass.buaa.edu.cn:8346/?loginName=a%2Bb"
                elif logical.path.endswith("login.action"):
                    case.assertEqual(parse_qs(logical.query)["phone"], ["a+b"])
                    body = {"STATUS": "0", "result": {"id": "u", "sessionId": "session"}}
                else:
                    case.assertIn("vpn=authorized", req.get_header("Cookie", ""))
                    case.assertEqual(req.get_header("Sessionid"), "session")
                    if logical.path.endswith("get_stu_course_sched.action"):
                        body = {"STATUS": "0", "result": [row()]}
                    elif logical.path.endswith("get_timestamp.action"):
                        body = {"STATUS": "0", "timestamp": "1778130000000"}
                    elif logical.path.endswith("stu_scan_sign.action"):
                        case.assertEqual(parse_qs(req.data.decode()), {"id": ["u"]})
                        case.assertEqual(parse_qs(logical.query)["courseSchedId"], ["s1"])
                        body = {"STATUS": "0", "result": {"stuSignStatus": "1"}}
                    else:
                        case.fail("Unexpected endpoint")
                raw = body if isinstance(body, str) else json.dumps(body)
                result = addinfourl(BytesIO(raw.encode()), headers, req.full_url, status)
                result.msg = "fixture"
                return result

        transport = WebVPNTransport()
        transport.opener = build_opener(HTTPCookieProcessor(transport.cookies), NoRedirect(), GatewayFixture())
        c = Client(transport, network="webvpn")
        c.login("student", " secret+value ")
        now = datetime(2026, 9, 14, 10, tzinfo=CHINA)
        schedule = Schedule("s1", "课程", "", "", now, now + timedelta(minutes=90), False)
        self.assertEqual(c.sign(schedule, now).status, "success")
        self.assertEqual(len(requests), 11)
        self.assertEqual(sum(r.get_method() == "POST" and "stu_scan_sign" in r.full_url for r in requests), 1)

    def test_mapping_preserves_protocol_port_query_and_fragment(self):
        cases = [("https", 8346), ("https", 8347), ("http", 8081)]
        for scheme, port in cases:
            raw = f"{scheme}://iclass.buaa.edu.cn:{port}/app/test?q=a%2Bb#part"
            mapped = gateway_url(raw)
            self.assertEqual(mapped, f"{GATEWAY}/{scheme}-{port}/{TOKENS['iclass.buaa.edu.cn']}/app/test?q=a%2Bb#part")
            self.assertEqual(gateway_url(mapped), mapped)
            self.assertEqual(original_url(mapped), raw)
        self.assertIn("/https/", gateway_url("https://sso.buaa.edu.cn:443/login"))

    def test_mapping_rejects_untrusted_hosts_ports_and_credentials(self):
        for url in ("https://evil.invalid", "https://d.buaa.edu.cn.evil.invalid/login",
                    "http://d.buaa.edu.cn/login", "https://d.buaa.edu.cn:8443/login",
                    "https://user:pass@sso.buaa.edu.cn/login", "https://iclass.buaa.edu.cn:22/",
                    "https://sso.buaa.edu.cn:0/login",
                    "https://d.buaa.edu.cn/https/unknown/login", "https://sso.buaa.edu.cn\\@evil.invalid/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                gateway_url(url)

    def test_encoded_portal_callbacks_preserve_request_url(self):
        for path in ("/login", "/wengine-vpn-token-login"):
            url = GATEWAY + "/https/" + TOKENS["d.buaa.edu.cn"] + path + "?ticket=a%2Bb&token=c%2Fd"
            self.assertEqual(gateway_url(url), url)
            self.assertEqual(original_url(url), GATEWAY + path + "?ticket=a%2Bb&token=c%2Fd")
        self.assertEqual(gateway_url(GATEWAY + "/token-login?token=a%2Bb"), GATEWAY + "/token-login?token=a%2Bb")

    def test_encoded_portal_does_not_allow_arbitrary_routes_or_protocols(self):
        token = TOKENS["d.buaa.edu.cn"]
        for path in (f"/https/{token}/admin", f"/http/{token}/login",
                     f"/https-8443/{token}/login", f"/https/{token}evil/login",
                     f"/https/{token}/https/{token}/login", "/token-login/evil"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                gateway_url(GATEWAY + path)

    def test_encoded_portal_form_never_receives_credentials(self):
        url = GATEWAY + "/https/" + TOKENS["d.buaa.edu.cn"] + "/login"
        c = Client(FakeTransport(web_response(FORM, url=url)), network="webvpn")
        with self.assertRaisesRegex(ClientError, "未发送凭据"):
            c.login("student", "password")
        self.assertEqual(len(c.transport.calls), 1)

    def login_client(self, *middle, result=None):
        transport = FakeTransport(web_response(FORM), *middle,
            web_response("", 302, "https://iclass.buaa.edu.cn:8346/?loginName=token%2Bvalue"),
            web_response(result or {"STATUS": "0", "result": {"id": "u", "sessionId": "business-session"}}))
        return Client(transport, network="webvpn")

    def test_login_preserves_form_and_uses_business_session(self):
        c = self.login_client(web_response("", 302, GATEWAY + "/login?ticket=fake"),
                              web_response("portal", url=GATEWAY + "/"))
        c.login(" user ", " secret ")
        self.assertEqual((c.user_id, c.session_id), ("u", "business-session"))
        call = c.transport.calls[1]
        self.assertEqual(call[2]["form"]["password"], " secret ")
        self.assertEqual(call[2]["form"]["execution"], "e&1")
        self.assertEqual(call[2]["form"]["hidden"], "keep")
        self.assertEqual(c.transport.calls[-1][2]["params"]["phone"], "token+value")
        self.assertTrue(c.transport.calls[-1][1].endswith(":8347/app/user/login.action"))

    def test_captcha_stops_before_sending_credentials(self):
        form = FORM.replace("</form>", '<input name="captcha"></form>')
        c = Client(FakeTransport(web_response(form)), network="webvpn")
        with self.assertRaisesRegex(ClientError, "验证码"):
            c.login("student", "password")
        self.assertEqual(len(c.transport.calls), 1)

    def test_wrong_form_action_never_receives_password(self):
        for action in ("https://evil.invalid/login", "https://iclass.buaa.edu.cn:8346/login",
                       "http://iclass.buaa.edu.cn:8081/login"):
            c = Client(FakeTransport(web_response(FORM.replace('action="/login"', f'action="{action}"'))), network="webvpn")
            with self.subTest(action=action), self.assertRaises(ClientError):
                c.login("student", "password")
            self.assertEqual(len(c.transport.calls), 1)

    def test_redirect_is_checked_before_extracting_login_name(self):
        c = self.login_client(web_response("portal", url=GATEWAY + "/"))
        c.transport.responses[2] = web_response("", 302, "https://evil.invalid/?loginName=secret")
        with self.assertRaisesRegex(ClientError, "学校服务范围"):
            c.login("student", "password")
        self.assertEqual(len(c.transport.calls), 3)
        self.assertEqual(c.session_id, "")

    def test_credential_post_is_not_replayed_on_307_or_308(self):
        for status in (307, 308):
            c = Client(FakeTransport(web_response(FORM), web_response("", status, "/other")), network="webvpn")
            with self.assertRaisesRegex(ClientError, "重发认证表单"):
                c.login("student", "password")
            self.assertEqual(len(c.transport.calls), 2)

    def test_failed_login_clears_old_identity(self):
        c = Client(FakeTransport(web_response(FORM), web_response("用户名或密码错误")), network="webvpn")
        c.user_id, c.session_id = "old", "old"
        with self.assertRaisesRegex(ClientError, "明确返回"):
            c.login("student", "password")
        self.assertEqual((c.user_id, c.session_id), ("", ""))

    def test_incomplete_business_login_never_retains_partial_identity(self):
        c = self.login_client(web_response("portal", url=GATEWAY + "/"),
                              result={"STATUS": "0", "result": {"id": "u"}})
        with self.assertRaisesRegex(ClientError, "会话标识"):
            c.login("student", "password")
        self.assertEqual((c.user_id, c.session_id), ("", ""))

    def test_redirect_loop_is_bounded(self):
        c = Client(FakeTransport(*[web_response("", 302, "/login") for _ in range(13)]), network="webvpn")
        with self.assertRaisesRegex(ClientError, "超过限制"):
            c.login("student", "password")
        self.assertEqual(len(c.transport.calls), 13)

    def test_expired_gateway_does_not_follow_or_replay_api(self):
        for reply in (web_response("", 302, GATEWAY + "/login"), web_response("<html>login</html>")):
            with patch.object(Transport, "request", return_value=reply) as request:
                with self.assertRaisesRegex(ClientError, "会话已失效"):
                    WebVPNTransport().request("POST", "http://iclass.buaa.edu.cn:8081/app/course/stu_scan_sign.action")
                self.assertEqual(request.call_count, 1)
                self.assertTrue(request.call_args.args[1].startswith(GATEWAY + "/http-8081/"))

    def test_transport_rejects_untrusted_target_before_network(self):
        with patch.object(Transport, "request") as request:
            with self.assertRaises(ClientError):
                WebVPNTransport().request("GET", "https://evil.invalid")
            request.assert_not_called()

    def test_worker_clones_gateway_cookie_without_sharing_mutable_state(self):
        parent = WebVPNTransport(7)
        parent.cookies.set_cookie(cookie())
        worker = parent.clone()
        self.assertIsInstance(worker, WebVPNTransport)
        self.assertEqual(worker.timeout, 7)
        self.assertIsNot(worker.opener, parent.opener)
        next(iter(worker.cookies)).value = "changed"
        self.assertEqual(next(iter(parent.cookies)).value, "fake-ticket")

    def test_parallel_date_fallback_preserves_gateway_and_business_session(self):
        c = Client(WebVPNTransport(), network="webvpn")
        c.transport.cookies.set_cookie(cookie())
        c.user_id, c.session_id = "u", "business-session"
        workers = []
        def read(worker, day):
            self.assertEqual(worker.network, "webvpn")
            self.assertEqual(worker.session_id, "business-session")
            self.assertIsInstance(worker.transport, WebVPNTransport)
            self.assertEqual(next(iter(worker.transport.cookies)).value, "fake-ticket")
            workers.append(worker)
            return []
        with patch.object(Client, "schedules", read):
            self.assertEqual(c._range_schedules(date(2026, 9, 14), date(2026, 9, 17)), [])
        self.assertEqual(len({id(w.transport) for w in workers}), 4)

    def test_sign_response_lost_is_read_back_without_duplicate_post(self):
        now = datetime(2026, 9, 14, 10, tzinfo=CHINA)
        schedule = Schedule("s1", "课程", "", "", now, now + timedelta(minutes=90), False)
        for final, expected in ((rows(row("1")), "success"), (ClientError("offline"), "unknown")):
            transport = FakeTransport(rows(row()), response({"STATUS": "0", "timestamp": "1778130000000"}),
                                      ClientError("timeout"), final)
            c = Client(transport, network="webvpn")
            c.user_id, c.session_id = "u", "session"
            self.assertEqual(c.sign(schedule, now).status, expected)
            posts = [call for call in transport.calls if call[0] == "POST"]
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0][1], "http://iclass.buaa.edu.cn:8081/app/course/stu_scan_sign.action")
            self.assertEqual(posts[0][2]["form"], {"id": "u"})
            self.assertNotIn("id", posts[0][2]["params"])

    def test_generic_success_requires_confirmation(self):
        now = datetime(2026, 9, 14, 10, tzinfo=CHINA)
        schedule = Schedule("s1", "课程", "", "", now, now + timedelta(minutes=90), False)
        for sign_reply in (response({"STATUS": "0"}), response("<html>成功</html>")):
            c = Client(FakeTransport(rows(row()), response({"STATUS": "0", "timestamp": "1778130000000"}),
                                     sign_reply, rows(row("0"))), network="webvpn")
            c.user_id, c.session_id = "u", "s"
            self.assertEqual(c.sign(schedule, now).status, "unknown")

    def test_config_and_cli_override_select_webvpn(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"student_number": "test", "password": "test", "network": "direct"}))
            with patch.object(cli, "Client") as factory:
                factory.return_value.schedules.return_value = []
                self.assertEqual(cli.main(["--config", str(path), "--network", "webvpn", "courses"]), 0)
                self.assertIsInstance(factory.call_args.args[0], WebVPNTransport)
                self.assertEqual(factory.call_args.kwargs["network"], "webvpn")
            for value in ("auto", True, None, [], {}):
                path.write_text(json.dumps({"network": value}))
                with self.assertRaisesRegex(ClientError, "network"):
                    cli.read_config(path)

    def test_desktop_mode_change_reauthenticates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = {"student_number": "test", "password": "secret"}
            path.write_text(json.dumps(config))
            with patch("buaa_sign.desktop.Client") as factory:
                factory.return_value.schedules.return_value = []
                service = DesktopService(path)
                self.assertTrue(service.handle({"action": "refresh"})["ok"])
                config["network"] = "webvpn"
                path.write_text(json.dumps(config))
                self.assertTrue(service.handle({"action": "refresh"})["ok"])
                self.assertEqual(factory.call_count, 2)
                self.assertIsInstance(factory.call_args.args[0], WebVPNTransport)
                self.assertEqual(factory.call_args.kwargs["network"], "webvpn")
                service.handle({"action": "refresh"})
                self.assertEqual(factory.call_count, 2)

    def test_menu_switch_persists_config_without_login_or_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = {"student_number": "test", "password": "secret", "term": "202620271"}
            path.write_text(json.dumps(config))
            with patch("buaa_sign.desktop.Client") as factory:
                service = DesktopService(path)
                reply = service.handle({"action": "set_network", "network": "webvpn"})
                self.assertTrue(reply["ok"])
                self.assertEqual(reply["network"], "webvpn")
                self.assertNotIn("secret", json.dumps(reply))
                self.assertEqual(json.loads(path.read_text()), {**config, "network": "webvpn"})
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(DesktopService(path).handle({"action": "snapshot"})["network"], "webvpn")
                self.assertFalse(service.handle({"action": "set_network", "network": "invalid"})["ok"])
                self.assertEqual(json.loads(path.read_text())["network"], "webvpn")
                factory.assert_not_called()

    def test_failed_setting_write_keeps_previous_mode_and_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"network":"direct"}')
            service = DesktopService(path)
            with patch("buaa_sign.desktop.os.replace", side_effect=OSError("denied")):
                reply = service.handle({"action": "set_network", "network": "webvpn"})
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["network"], "direct")
            self.assertEqual(json.loads(path.read_text())["network"], "direct")
            self.assertEqual(list(Path(directory).iterdir()), [path])
class TLSVerificationTests(unittest.TestCase):
    def test_self_signed_https_is_rejected_before_sending_password(self):
        class Handler(BaseHTTPRequestHandler):
            received = False
            def do_POST(self):
                Handler.received = True
                self.send_response(200); self.end_headers()
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory:
            key, cert = Path(directory) / "key.pem", Path(directory) / "cert.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                # Map only in this test to a real local HTTPS endpoint; the
                # production transport's urllib certificate verification runs.
                with patch("buaa_sign.client.gateway_url", return_value=f"https://127.0.0.1:{server.server_port}/login"):
                    with self.assertRaises(ClientError) as caught:
                        WebVPNTransport().request("POST", "https://sso.buaa.edu.cn/login", form={"password": "fake"})
                    self.assertIsInstance(caught.exception.__cause__, URLError)
                    self.assertIsInstance(caught.exception.__cause__.reason, ssl.SSLCertVerificationError)
                self.assertFalse(Handler.received)
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == "__main__":
    unittest.main()
