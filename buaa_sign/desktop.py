"""按用户操作处理 JSON 行消息；无后台刷新、无启动网络请求。"""
import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
import hashlib
import os
import tempfile
from pathlib import Path
import sys

from .cli import PROJECT, read_config
from .client import CHINA, Client, ClientError, Transport, Schedule


class DesktopService:
    def __init__(self, config_path, client_factory=None):
        self.config_path = config_path
        self.client_factory = client_factory or (lambda timeout: Client(Transport(timeout)))
        self.client = None
        self.identity = None
        self.login_at = None
        self.rows = []
        self.day = None
        self.updated = None
        self.overrides = {}
        self.week_start = None
        self.term = None
        self.semester_updated = None
        self.cache_key = None
        self.cache_warning = None

    @staticmethod
    def configured_term(config):
        now = datetime.now(CHINA)
        year, month = now.year, now.month
        return config.get("term") or (f"{year}{year+1}1" if month >= 9 else
                                      f"{year-1}{year}1" if month == 1 else f"{year-1}{year}2")

    def snapshot(self):
        return {
            "term": self.term,
            "semester_updated": self.semester_updated,
            "cache_warning": self.cache_warning,
            "date": self.day.isoformat() if self.day else None,
            "week_start": self.week_start.isoformat() if self.week_start else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "courses": [{"id": s.id, "name": s.name, "teacher": s.teacher,
                         "classroom": s.classroom, "start": s.start.isoformat(),
                         "end": s.end.isoformat(), "signed": s.signed} for s in self.rows],
        }

    def select_cache(self, number, config):
        scope = json.dumps([number, self.configured_term(config), config.get("semester_start"), config.get("semester_end")])
        key = hashlib.sha256(scope.encode()).hexdigest()
        if self.cache_key == key:
            return
        self.rows, self.day, self.updated, self.week_start, self.term = [], None, None, None, None
        self.semester_updated = None
        self.cache_key = key
        path = self.config_path.parent / ".cache" / f"semester-{key}.json"
        try:
            data = json.loads(path.read_text())
            if data.get("version") != 1 or data.get("term") != self.configured_term(config):
                return
            rows = [Schedule(r["id"], r["name"], r["teacher"], r["classroom"],
                             datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"]), r["signed"])
                    for r in data["courses"]]
            day = date.fromisoformat(data["date"]) if data.get("date") else None
            updated = datetime.fromisoformat(data["updated"]) if data.get("updated") else None
            self.rows, self.term, self.day, self.updated = rows, data["term"], day, updated
            self.semester_updated = data.get("semester_updated")
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Corrupt/missing cache must never trigger an automatic semester query.

    def save_cache(self):
        try:
            self._save_cache()
        except OSError:
            self.cache_warning = "本地缓存写入失败，退出后需手动重新加载学期。"

    def _save_cache(self):
        if not self.term or not self.cache_key:
            return
        directory = self.config_path.parent / ".cache"
        directory.mkdir(mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="semester-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"version": 1, **self.snapshot()}, stream, ensure_ascii=False)
            os.replace(temporary, directory / f"semester-{self.cache_key}.json")
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def authenticate(self, request):
        config = read_config(self.config_path) if self.config_path.exists() else {}
        for key in ("student_number", "password"):
            value = request.get(key)
            if isinstance(value, str) and value:
                self.overrides[key] = value
        number = config.get("student_number", "").strip() or self.overrides.get("student_number", "").strip()
        password = config.get("password") or self.overrides.get("password", "")
        missing = [k for k, v in (("student_number", number), ("password", password)) if not v]
        if missing:
            return {"ok": False, "needs_credentials": missing, "message": "请填写缺少的账号信息。", **self.snapshot()}
        identity = (number, password, config.get("timeout", 15))
        if self.identity and self.identity != identity:
            # Never apply a cached course from one account to another account.
            self.rows, self.day, self.updated = [], None, None
            self.week_start = None
            self.term = None
            self.cache_key = None
        self.select_cache(number, config)
        if self.client is None or self.identity != identity or datetime.now(CHINA) - self.login_at > timedelta(minutes=25):
            client = self.client_factory(config.get("timeout", 15))
            client.login(number, password)
            self.client, self.identity, self.login_at = client, identity, datetime.now(CHINA)
        return None

    def handle(self, request):
        try:
            if not isinstance(request, dict):
                raise ClientError("请求格式错误。")
            action = request.get("action")
            if action == "snapshot":
                return {"ok": True, **self.snapshot()}
            if action not in ("refresh", "refresh_week", "refresh_semester", "sign"):
                raise ClientError("不支持的操作。")
            missing = self.authenticate(request)
            if missing:
                return missing
            now = datetime.now(CHINA)
            if action == "refresh_semester":
                config = read_config(self.config_path) if self.config_path.exists() else {}
                term = self.configured_term(config)
                bounds = {k: config[v] for k, v in (("start", "semester_start"), ("end", "semester_end")) if config.get(v)}
                rows = self.client.semester_schedules(term, **bounds)
                self.rows, self.term = rows, term
                self.week_start, self.day, self.updated = None, now.date(), datetime.now(CHINA)
                self.semester_updated = self.updated.isoformat()
                self.save_cache()
                return {"ok": True, "message": f"学期 {term} 完整课表已更新，共 {len(rows)} 节课", **self.snapshot()}
            if action == "refresh_week":
                try:
                    requested = date.fromisoformat(request.get("week_start", now.date().isoformat()))
                except (ValueError, TypeError):
                    raise ClientError("周日期格式错误。")
                monday = requested - timedelta(days=requested.weekday())
                rows = {}
                for offset in range(7):
                    for row in self.client.schedules(monday + timedelta(days=offset)):
                        rows[row.id] = row
                # Commit only after all seven queries succeed; keep the previous week on failure.
                self.rows = sorted(rows.values(), key=lambda s: (s.start, s.id))
                self.term = None
                self.week_start, self.day, self.updated = monday, now.date(), datetime.now(CHINA)
                return {"ok": True, "message": "本周课表已更新", **self.snapshot()}
            if action == "refresh":
                rows = self.client.schedules(now.date())
                if self.term or (self.week_start and self.week_start <= now.date() < self.week_start + timedelta(days=7)):
                    combined = {s.id: s for s in self.rows if s.start.date() != now.date()}
                    combined.update({s.id: s for s in rows})
                    rows = sorted(combined.values(), key=lambda s: (s.start, s.id))
                else:
                    self.week_start = None
                self.rows, self.day, self.updated = rows, now.date(), datetime.now(CHINA)
                self.save_cache()
                return {"ok": True, "message": "今日课程与签到状态已更新", **self.snapshot()}
            if self.term is None and ((self.week_start is None and self.day != now.date()) or
                    (self.week_start is not None and not self.week_start <= now.date() < self.week_start + timedelta(days=7))):
                raise ClientError("请先手动刷新今天的课表。")
            schedule = next((s for s in self.rows if s.id == request.get("id")), None)
            if schedule is None:
                raise ClientError("未找到课程，请手动刷新课表。")
            if not schedule.eligible(now):
                raise ClientError("课程已签到、不在签到时间窗口内，或状态待确认。")
            result = self.client.sign(schedule)
            signed = True if result.status == "success" else (None if result.status == "unknown" else result.schedule.signed)
            self.rows = [replace(result.schedule, signed=signed) if s.id == schedule.id else s for s in self.rows]
            self.save_cache()
            return {"ok": result.status in ("success", "skipped"), "sign_status": result.status,
                    "course_id": schedule.id, "message": result.message, **self.snapshot()}
        except ClientError as exc:
            # The next explicit action may log in again; no automatic request or retry.
            self.client = None
            return {"ok": False, "message": str(exc), **self.snapshot()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=PROJECT / "config.json")
    args = parser.parse_args()
    service = DesktopService(args.config)
    for line in sys.stdin:
        try:
            result = service.handle(json.loads(line))
        except (ValueError, TypeError):
            result = {"ok": False, "message": "请求格式错误。", **service.snapshot()}
        except Exception:
            # Never serialize a traceback that may expose credentials or server bodies.
            result = {"ok": False, "message": "操作异常，请手动刷新后重试；如已提交签到，请核对考勤记录。", **service.snapshot()}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
