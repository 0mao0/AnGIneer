"""startup_guard 单测：坏报告 TTL 后台重探自愈 + 重探节流。"""
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core import startup_guard as sg  # noqa: E402
from docs_core.startup_guard import VectorGuardReport  # noqa: E402


def _bad_report() -> VectorGuardReport:
    report = VectorGuardReport()
    report.add_error("向量库不可访问: Unexpected Response: 502")
    return report


class StartupGuardRecheckTests(unittest.TestCase):
    def setUp(self):
        self._reset_globals()

    def tearDown(self):
        self._reset_globals()

    @staticmethod
    def _reset_globals():
        sg._last_report = None
        sg._last_check_monotonic = 0.0

    def test_none_report_no_warning(self):
        self.assertIsNone(sg.get_retrieve_warning())

    def test_healthy_report_no_warning(self):
        sg._save_report(VectorGuardReport())
        self.assertIsNone(sg.get_retrieve_warning())

    def test_fresh_bad_report_warns_without_recheck(self):
        sg._save_report(_bad_report())  # 刚落盘，间隔内不重探
        self.assertIn("向量库健康检查异常", sg.get_retrieve_warning())

    def test_stale_bad_report_returns_old_text_and_triggers_recheck(self):
        sg._save_report(_bad_report())
        sg._last_check_monotonic -= 61.0  # 伪装成一分钟前探测过
        with patch.object(sg, "run_vector_startup_guard") as recheck:
            warning = sg.get_retrieve_warning()  # 本次调用仍返回旧横幅，同时触发重探
            for t in threading.enumerate():
                if t.name == "vector-guard-recheck":
                    t.join(timeout=5)
        self.assertIn("502", warning)
        recheck.assert_called_once()

    def test_recheck_self_heals_warning(self):
        sg._save_report(_bad_report())
        sg._last_check_monotonic -= 61.0
        probe_observed = threading.Event()

        def _recheck():
            probe_observed.wait(timeout=5)  # 挂住重探，钉住「本次调用仍返回旧横幅」的窗口
            sg._save_report(VectorGuardReport())  # 重探发现已恢复

        with patch.object(sg, "run_vector_startup_guard", side_effect=_recheck):
            thread = sg._maybe_schedule_recheck()
            self.assertIsNotNone(thread)
            self.assertIsNotNone(sg.get_retrieve_warning())  # 重探未落地：旧横幅仍在
            probe_observed.set()
            thread.join(timeout=5)
        self.assertIsNone(sg.get_retrieve_warning())  # 重探落地：横幅自愈

    def test_recheck_throttled_while_unhealthy(self):
        sg._save_report(_bad_report())
        sg._last_check_monotonic -= 61.0
        with patch.object(sg, "run_vector_startup_guard"):  # no-op：不落新报告，保持坏状态
            first = sg._maybe_schedule_recheck()
            second = sg._maybe_schedule_recheck()  # 占坑生效：间隔内第二次不起线程
            first.join(timeout=5)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_still_unhealthy_recheck_refreshes_error(self):
        sg._save_report(_bad_report())
        sg._last_check_monotonic -= 61.0
        with patch.object(sg, "run_vector_startup_guard",
                          side_effect=lambda: sg._save_report(_bad_report())):
            thread = sg._maybe_schedule_recheck()
            thread.join(timeout=5)
        self.assertIsNotNone(sg.get_retrieve_warning())  # 仍不可达：横幅继续，错误已刷新


if __name__ == "__main__":
    unittest.main()
