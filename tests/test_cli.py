from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from buaa_sign.cli import main
from buaa_sign.client import CHINA, Course, Schedule, SignResult


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"student_number": "test", "password": "test", "term": "202620271"}))
        self.output = io.StringIO()

    def run_cli(self, args):
        with redirect_stdout(self.output), redirect_stderr(self.output), patch.dict(os.environ, {}, clear=True):
            return main(["--config", str(self.config), *args])

    def schedule(self):
        now = datetime.now(CHINA)
        return Schedule("s1", "测试课", "测试教师", "教室", now, now + timedelta(hours=1), False)

    @patch("buaa_sign.cli.Client")
    def test_courses_never_submits_attendance(self, factory):
        client = factory.return_value
        client.schedules.return_value = [self.schedule()]
        self.assertEqual(self.run_cli(["courses"]), 0)
        client.schedules.assert_called_once_with(datetime.now(CHINA).date())
        client.sign.assert_not_called()
        self.assertIn("测试课", self.output.getvalue())

    @patch("buaa_sign.cli.Client")
    def test_dry_run_displays_without_signing(self, factory):
        client = factory.return_value
        client.candidates.return_value = [self.schedule()]
        self.assertEqual(self.run_cli(["sign", "--dry-run"]), 0)
        self.assertIn("测试课", self.output.getvalue())
        client.sign.assert_not_called()

    @patch("buaa_sign.cli.Client")
    def test_yes_submits_and_unknown_is_nonzero(self, factory):
        client = factory.return_value
        schedule = self.schedule()
        client.candidates.return_value = [schedule]
        client.sign.return_value = SignResult(schedule, "unknown", "待确认")
        self.assertEqual(self.run_cli(["sign", "--yes"]), 1)
        client.sign.assert_called_once_with(schedule)

    @patch("buaa_sign.cli.sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    @patch("buaa_sign.cli.Client")
    def test_cancel_does_not_sign(self, factory, _input, _tty):
        client = factory.return_value
        client.candidates.return_value = [self.schedule()]
        self.assertEqual(self.run_cli(["sign"]), 0)
        client.sign.assert_not_called()

    @patch("buaa_sign.cli.sys.stdin.isatty", return_value=False)
    @patch("buaa_sign.cli.Client")
    def test_noninteractive_requires_explicit_submission(self, factory, _tty):
        client = factory.return_value
        client.candidates.return_value = [self.schedule()]
        self.assertEqual(self.run_cli(["sign"]), 1)
        client.sign.assert_not_called()

    @patch("buaa_sign.cli.Client")
    def test_bad_config_is_rejected_before_login(self, factory):
        for config in ([], {"password": 123}, {"timeout": -1}, {"timeout": float("nan")}):
            self.config.write_text(json.dumps(config))
            self.assertEqual(self.run_cli(["courses"]), 1)
        factory.assert_not_called()

    @patch("buaa_sign.cli.sys.stdin.isatty", return_value=False)
    @patch("buaa_sign.cli.Client")
    def test_missing_credentials_fails_without_network_or_traceback(self, factory, _tty):
        self.config.write_text('{"term":"202620271"}')
        self.assertEqual(self.run_cli(["courses"]), 1)
        factory.assert_not_called()
        self.assertNotIn("Traceback", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
