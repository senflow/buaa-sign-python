import argparse
from getpass import getpass
import json
import math
from pathlib import Path
import sys

from datetime import datetime

from .client import CHINA, Client, ClientError, Transport, WebVPNTransport

PROJECT = Path(__file__).resolve().parent.parent


def read_config(path):
    if not path.exists():
        raise ClientError(f"配置文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClientError("无法读取配置文件，请检查文件权限和 JSON 格式。") from exc
    if not isinstance(data, dict):
        raise ClientError("配置文件必须为 JSON 对象。")
    for field in ("student_number", "password", "term"):
        if field in data and not isinstance(data[field], str):
            raise ClientError(f"配置项 {field} 必须是字符串。")
    timeout = data.get("timeout", 15)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ClientError("timeout 必须为正数。")
    if data.get("network", "direct") not in ("direct", "webvpn"):
        raise ClientError("network 必须为 direct 或 webvpn。")
    return data


def credentials(config):
    number = config.get("student_number", "").strip()
    password = config.get("password", "")
    if not number:
        if not sys.stdin.isatty():
            raise ClientError("缺少学号；请在 config.json 中填写 student_number，或在交互终端输入。")
        number = input("请输入学号：").strip()
    if not password:
        if not sys.stdin.isatty():
            raise ClientError("缺少密码；请在 config.json 中填写 password，或在交互终端输入。")
        password = getpass("请输入统一认证密码（不回显）：")
    return number, password


def show_courses(courses):
    if not courses:
        print("今天没有课程。")
        return
    print(f"今天共 {len(courses)} 节课（北京时间）：")
    for i, c in enumerate(courses, 1):
        state = {True: "已签到", False: "未签到", None: "状态未知"}[c.signed]
        print(f"{i}. {c.name} | {c.start:%H:%M}–{c.end:%H:%M}"
              f" | 教师：{c.teacher or '未提供'} | 教室：{c.classroom or '未提供'} | {state}")


def show_candidates(schedules):
    if not schedules:
        print("当前没有处于签到时间窗口且明确未签到的课程。")
        return
    print(f"当前有 {len(schedules)} 节课程处于签到时间窗口（北京时间）：")
    for i, s in enumerate(schedules, 1):
        print(f"{i}. {s.name} | {s.start:%Y-%m-%d %H:%M} 至 {s.end:%Y-%m-%d %H:%M}"
              f" | 教师：{s.teacher or '未提供'} | 教室：{s.classroom or '未提供'} | 安排 ID：{s.id}")
    print("时间窗口为课前 10 分钟至下课；是否开放签到由服务端决定。")


def parser():
    p = argparse.ArgumentParser(description="北航 iClass：查看今天全部课程、查看当前课程并签到")
    p.add_argument("--config", type=Path, help="配置文件路径（默认项目目录 config.json）")
    p.add_argument("--network", choices=("direct", "webvpn"), help="网络模式（覆盖配置文件）")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("courses", help="查看今天全部课程")
    sign = sub.add_parser("sign", help="查看当前处于时间窗口的课程并签到")
    sign.add_argument("--dry-run", action="store_true", help="只查看课程，不提交签到")
    sign.add_argument("--yes", action="store_true", help="展示后直接签到，不再交互确认")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        config_path = args.config or PROJECT / "config.json"
        config = read_config(config_path) if args.config or config_path.exists() else {}
        command = args.command
        if command is None:
            if not sys.stdin.isatty():
                p.print_help()
                return 2
            print("1. 查看今天全部课程\n2. 查看当前时段课程并签到")
            choice = input("请选择（1/2）：").strip()
            if choice not in {"1", "2"}:
                raise ClientError("请选择 1 或 2。")
            command = {"1": "courses", "2": "sign"}[choice]
        number, password = credentials(config)
        network = args.network or config.get("network", "direct")
        transport = WebVPNTransport if network == "webvpn" else Transport
        client = Client(transport(config.get("timeout", 15)), network=network)
        print("正在登录…")
        client.login(number, password)
        password = None
        if command == "courses":
            today = datetime.now(CHINA).date()
            print(f"日期：{today}（北京时间）")
            show_courses(client.schedules(today))
            return 0
        schedules = client.candidates()
        show_candidates(schedules)
        if not schedules or getattr(args, "dry_run", False):
            return 0
        if not getattr(args, "yes", False):
            if not sys.stdin.isatty():
                raise ClientError("非交互模式请使用 --dry-run 查看，或 --yes 提交签到。")
            if input("为以上课程提交签到？[y/N]：").strip().lower() not in {"y", "yes"}:
                print("已取消，未提交签到。")
                return 0
        errors = False
        labels = {"success": "成功", "failed": "失败", "unknown": "待确认", "skipped": "跳过"}
        for schedule in schedules:
            try:
                result = client.sign(schedule)
                print(f"[{labels[result.status]}] {schedule.name}：{result.message}")
                errors |= result.status in {"failed", "unknown"}
            except ClientError as exc:
                errors = True
                print(f"[失败] {schedule.name}：{exc}")
        return 1 if errors else 0
    except (ClientError, EOFError) as exc:
        print(f"错误：{exc or '输入已关闭。'}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断。如已提交签到请求，请在 iClass 核对考勤记录。", file=sys.stderr)
        return 130
