"""iClass 客户端：不保存凭据，不自动重试签到请求。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")
SSO = "https://sso.buaa.edu.cn/login"
SERVICE = "https://iclass.buaa.edu.cn:8346/"
LOGIN = SERVICE + "eschool/app/user/login_buaa.do"
QUERY = "https://iclass.buaa.edu.cn:8347"
SIGN = "http://iclass.buaa.edu.cn:8081/eschool"


class ClientError(Exception):
    """可以直接显示给用户的错误，不包含凭据或带 token 的 URL。"""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class Response:
    status: int
    url: str
    headers: dict
    body: str


class Transport:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), NoRedirect())

    def request(self, method, url, *, params=None, form=None, headers=None):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        data = urlencode(form).encode("utf-8") if form is not None else None
        # A zero-length POST body is required by some servlet deployments.
        if method == "POST" and data is None:
            data = b""
        req_headers = {"User-Agent": "BUAA-Sign-Python/0.1", **(headers or {})}
        if form is not None:
            req_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        req = Request(url, data=data, headers=req_headers, method=method)
        try:
            try:
                response = self.opener.open(req, timeout=self.timeout)
            except HTTPError as exc:
                response = exc
            with response:
                return Response(response.code, response.url,
                                {k.lower(): v for k, v in response.headers.items()},
                                response.read().decode("utf-8", errors="replace"))
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            raise ClientError("网络请求失败或超时，请检查校园网连接及代理设置。") from exc


class ExecutionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.execution = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and fields.get("name") == "execution":
            self.execution = fields.get("value")


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    teacher: str


@dataclass(frozen=True)
class Schedule:
    id: str
    name: str
    teacher: str
    classroom: str
    start: datetime
    end: datetime
    signed: bool | None

    def eligible(self, now):
        if now.tzinfo is None:
            raise ValueError("时间必须包含时区")
        return self.signed is False and self.start - timedelta(minutes=10) <= now < self.end


@dataclass(frozen=True)
class SignResult:
    schedule: Schedule
    status: str  # success / failed / unknown / skipped
    message: str


def validate_term(term):
    if not re.fullmatch(r"\d{8}[12]", term or ""):
        raise ClientError("学期编号格式错误，例如 202620271（2026–2027 学年第一学期）。")
    if int(term[4:8]) != int(term[:4]) + 1:
        raise ClientError("学期编号的两个年份必须连续。")
    return term


def _identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("缺少 ID")
    return str(value)


def _time(value):
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=CHINA) if dt.tzinfo is None else dt.astimezone(CHINA)


class Client:
    def __init__(self, transport=None):
        self.transport = transport or Transport()
        self.user_id = ""
        self.session_id = ""

    @staticmethod
    def _json(response):
        if response.status != 200:
            raise ClientError(f"接口返回 HTTP {response.status}，可能需要重新登录或接口已变化。")
        try:
            data = json.loads(response.body)
        except ValueError as exc:
            raise ClientError("接口没有返回 JSON，可能登录已失效或接口已变化。") from exc
        if not isinstance(data, dict):
            raise ClientError("接口返回的数据结构异常。")
        return data

    @staticmethod
    def _check(data, *, empty_ok=False):
        status = str(data.get("STATUS", ""))
        if status == "0":
            return
        if empty_ok and status == "2":
            return
        # Do not echo arbitrary server bodies, which may contain identifiers/tokens.
        code = status if re.fullmatch(r"\d{1,4}", status) else "缺失或未知"
        raise ClientError(f"服务端未确认成功（STATUS={code}），可能会话失效或尚未开启签到。")

    @staticmethod
    def _redirect_target(response):
        location = response.headers.get("location")
        if not location:
            raise ClientError("认证跳转缺少 Location。")
        target = urljoin(response.url, location)
        parsed = urlsplit(target)
        if (parsed.scheme not in ("https", "http") or
                parsed.hostname not in {"sso.buaa.edu.cn", "iclass.buaa.edu.cn", "uc.buaa.edu.cn"} or
                parsed.username or parsed.password):
            raise ClientError("认证跳转地址不在支持的学校服务范围内。")
        return target

    @staticmethod
    def _login_error(response):
        # Match explicit messages only; do not print HTML, form tokens or redirect queries.
        if any(text in response.body for text in ("用户名或密码错误", "用户名或密码不正确", "账号或密码错误")):
            return "统一认证页面明确返回账号或密码错误，请核对当前使用的凭据。"
        if 'id="continueForm"' in response.body or "id='continueForm'" in response.body:
            return "统一认证要求处理密码到期或账号安全提示，请在学校网页处理后重试。"
        if response.status in (401, 403, 423, 429):
            return f"统一认证拒绝请求（HTTP {response.status}），请检查账号状态或稍后重试；不能据此判断密码错误。"
        return None

    def _follow_login(self, response):
        for _ in range(12):
            if response.status not in (301, 302, 303, 307, 308):
                return None, response
            target = self._redirect_target(response)
            login_name = parse_qs(urlsplit(target).query).get("loginName", [None])[0]
            if login_name:
                return login_name, response
            response = self.transport.request("GET", target)
        raise ClientError("认证跳转次数超过限制，登录未完成。")

    def login(self, student_number, password):
        self.user_id = self.session_id = ""
        if not student_number.strip() or not password:
            raise ClientError("学号和密码不能为空。")
        response = self.transport.request("GET", SSO, params={"service": SERVICE})
        parser = ExecutionParser()
        parser.feed(response.body)
        if response.status != 200 or not parser.execution:
            raise ClientError("无法获取登录表单，请检查网络或学校认证页面是否变化。")
        response = self.transport.request("POST", SSO, params={"service": SERVICE}, form={
            "username": student_number.strip(), "password": password,
            "submit": "登录", "type": "username_password",
            "execution": parser.execution, "_eventId": "submit",
        })
        login_name, response = self._follow_login(response)
        if not login_name:
            error = self._login_error(response)
            if error:
                raise ClientError(error)
            parser = ExecutionParser()
            parser.feed(response.body)
            if parser.execution:
                raise ClientError("统一认证仍停留在登录表单，未完成登录；可能需要额外验证，不能确定是密码错误。")
            if response.status != 200:
                raise ClientError(f"认证未完成（HTTP {response.status}），尚未取得 iClass 登录凭据。")
            # Some deployments end SSO at a landing page; explicitly enter My Center.
            response = self.transport.request("GET", SERVICE, params={"type": "jumpMyCenter"})
            login_name, response = self._follow_login(response)
            if not login_name:
                error = self._login_error(response)
                raise ClientError(error or "未取得 iClass 的 loginName：统一认证跳转或 iClass 入口未完成；这不等于密码错误。")
        data = self._json(self.transport.request("GET", LOGIN, params={
            "phone": login_name, "password": "", "verificationType": "2",
            "verificationUrl": "", "userLevel": "1",
        }))
        self._check(data)
        try:
            self.user_id = _identifier(data["result"]["id"])
            # Current protocol uses loginName as Sessionid; old Java used result.sessionId.
            self.session_id = login_name
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError("登录响应缺少用户 ID。") from exc

    def _api(self, base, path, params=None):
        if not self.user_id or not self.session_id:
            raise ClientError("请先登录。")
        return self._json(self.transport.request(
            "POST", base + path, params={**(params or {}), "id": self.user_id},
            headers={"Sessionid": self.session_id}))

    def _items(self, path, params):
        data = self._api(QUERY, path, params)
        self._check(data, empty_ok=True)
        if str(data.get("STATUS")) == "2":
            return []
        result = data.get("result")
        if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
            raise ClientError("课程列表格式异常，未将其当成无课。")
        return result

    def courses(self, term):
        rows = self._items("/app/choosecourse/get_myall_course.action", {
            "user_type": "1", "xq_code": validate_term(term),
        })
        result = {}
        try:
            for row in rows:
                course = Course(_identifier(row["course_id"]), str(row["course_name"]),
                                str(row.get("teacher_name") or ""))
                result[course.id] = course
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError("课程数据缺少必要字段。") from exc
        return sorted(result.values(), key=lambda c: (c.name, c.id))

    def schedules(self, day: date):
        rows = self._items("/app/course/get_stu_course_sched.action", {"dateStr": day.strftime("%Y%m%d")})
        result = {}
        try:
            for row in rows:
                state = str(row.get("signStatus", ""))
                item = Schedule(_identifier(row["id"]), str(row["courseName"]),
                                str(row.get("teacherName") or ""), str(row.get("classroomName") or ""),
                                _time(row["classBeginTime"]), _time(row["classEndTime"]),
                                {"0": False, "1": True}.get(state))
                if item.end <= item.start:
                    raise ValueError("课程起止时间异常")
                result[item.id] = item
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError("课表缺少必要字段或时间格式异常，停止签到。") from exc
        return sorted(result.values(), key=lambda s: (s.start, s.id))

    def semester_schedules(self, term, *, start=None, end=None):
        """Discover teaching dates from all course schedules, then get full daily records.

        The detail API does not reliably include end times/classrooms. Never guess
        durations: query each distinct teaching date once to obtain complete data.
        """
        dates = {}
        courses = self.courses(term)
        if not courses:
            # Some graduate accounts have schedules but an empty course catalog.
            # Use explicit bounds, or the configured academic half-year, rather
            # than interpreting an empty catalog as an empty semester.
            first, second = int(term[:4]), int(term[4:8])
            try:
                begin = date.fromisoformat(start) if start else (date(first, 9, 1) if term[-1] == "1" else date(second, 2, 1))
                finish = date.fromisoformat(end) if end else (date(second, 1, 31) if term[-1] == "1" else date(second, 8, 31))
            except (ValueError, TypeError) as exc:
                raise ClientError("学期起止日期格式错误，请使用 YYYY-MM-DD。") from exc
            if not 0 <= (finish - begin).days <= 365:
                raise ClientError("学期日期范围必须为 1 至 366 天。")
            return self._range_schedules(begin, finish)
        for course in courses:
            rows = self._items("/app/my/get_my_course_sign_detail.action", {"courseId": course.id})
            try:
                for row in rows:
                    day = _time(row["classBeginTime"]).date()
                    schedule_id = _identifier(row["courseSchedId"])
                    dates.setdefault(day, set()).add(schedule_id)
            except (KeyError, TypeError, ValueError) as exc:
                raise ClientError("学期课程安排缺少日期或安排 ID，无法确认完整课表。") from exc
        result = {}
        for day, expected in sorted(dates.items()):
            rows = {s.id: s for s in self.schedules(day)}
            if not expected.issubset(rows):
                raise ClientError(f"{day} 的课程详情不完整，保留上次课表，请稍后重试。")
            result.update({key: rows[key] for key in expected})
        return sorted(result.values(), key=lambda s: (s.start, s.id))

    def _range_schedules(self, begin, finish):
        from concurrent.futures import ThreadPoolExecutor

        def read(day):
            # A separate transport per request avoids sharing mutable cookie state.
            client = Client(Transport(getattr(self.transport, "timeout", 15)))
            client.user_id, client.session_id = self.user_id, self.session_id
            return client.schedules(day)

        result = {}
        days = [begin + timedelta(days=i) for i in range((finish - begin).days + 1)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            for offset in range(0, len(days), 4):
                # Submit a bounded batch; after a failure don't queue more dates.
                for rows in executor.map(read, days[offset:offset + 4]):
                    result.update({s.id: s for s in rows})
        return sorted(result.values(), key=lambda s: (s.start, s.id))

    def candidates(self, now=None):
        now = now or datetime.now(CHINA)
        # Include the previous date for a course that crosses midnight.
        rows = self.schedules(now.astimezone(CHINA).date())
        if now.astimezone(CHINA).hour == 0:
            rows += self.schedules(now.astimezone(CHINA).date() - timedelta(days=1))
        return list({s.id: s for s in rows if s.eligible(now)}.values())

    def sign(self, schedule, now=None):
        # Re-read status after the user has inspected the candidate list.
        fresh = next((s for s in self.schedules(schedule.start.date()) if s.id == schedule.id), None)
        if fresh is None or not fresh.eligible(now or datetime.now(CHINA)):
            return SignResult(fresh or schedule, "skipped", "课程已签到、不在时间窗口内，或状态无法确认，已跳过。")
        data = self._api(SIGN, "/app/common/get_timestamp.action")
        self._check(data)
        timestamp = data.get("timestamp")
        if timestamp is None and isinstance(data.get("result"), dict):
            timestamp = data["result"].get("timestamp")
        if isinstance(timestamp, bool) or not re.fullmatch(r"\d{10,16}", str(timestamp)):
            raise ClientError("无法获取有效的服务器时间戳，未提交签到。")
        if not fresh.eligible(now or datetime.now(CHINA)):
            return SignResult(fresh, "skipped", "课程已离开签到时间窗口，未提交签到。")
        # Do not retry this POST, even if its response is lost.
        try:
            data = self._api(SIGN, "/app/course/stu_scan_sign.action", {
                "courseSchedId": fresh.id, "timestamp": timestamp,
            })
        except ClientError:
            return self._verify(fresh, "签到响应丢失或异常")
        if str(data.get("STATUS", "")) != "0":
            return SignResult(fresh, "failed", "服务端未确认签到成功，可能未开启签到或会话失效。")
        result = data.get("result")
        if isinstance(result, dict) and str(result.get("stuSignStatus")) == "1":
            return SignResult(fresh, "success", "服务端确认签到成功。")
        return self._verify(fresh, "签到响应未提供明确成功标记")

    def _verify(self, schedule, reason):
        try:
            rows = self.schedules(schedule.start.date())
            if any(s.id == schedule.id and s.signed is True for s in rows):
                return SignResult(schedule, "success", "重新查询课表，服务端记录为已签到。")
        except ClientError:
            pass
        return SignResult(schedule, "unknown", reason + "；结果待确认，请查看 iClass 考勤记录，未自动重试。")
