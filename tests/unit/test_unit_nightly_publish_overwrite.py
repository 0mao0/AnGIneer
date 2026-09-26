"""结论落盘的覆盖规矩：error 档不得盖掉同日已出的 green/red 结论。

2026-09-26 实踩：00:32 一版完整结论（连 report.md）被 03:17 定时跑的 error 档原地盖掉，
页面上只剩「中断于 1040/1040」、真结论整个丢。同一天本就允许多条派发（管理页「立即运行」
+ 01:00 定时），落盘必须按「有结论优先」而不是「最后一次写了什么」。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
P = os.path.join(ROOT, "services", "evals-core", "src")
if P not in sys.path:
    sys.path.insert(0, P)

from evals_core.nightly import archive  # noqa: E402

DATE = "2026-09-26"


def _entry(state, note=""):
    return {"date": DATE, "state": state, "note": note, "run_id": f"run-{state}"}


class PublishDayOverwriteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))

    def _dir(self):
        return self.root / DATE

    def _read(self, name="nightly.json"):
        return json.loads((self._dir() / name).read_text(encoding="utf-8"))

    def test_error_after_conclusion_lands_in_sidecar_and_keeps_conclusion(self):
        archive.publish_day(_entry("green"), "# 报告正文", root=self.root)
        archive.publish_day(_entry("error", "判分补判轮数耗尽"), None, root=self.root)
        self.assertEqual(self._read()["state"], "green")                      # 结论没被盖掉
        self.assertEqual(self._read(archive.ERROR_SIDECAR)["state"], "error")  # 失败详情也没丢
        self.assertEqual((self._dir() / "report.md").read_text(encoding="utf-8"), "# 报告正文")

    def test_error_without_any_conclusion_still_occupies_main_slot(self):
        """「当天必有一条结论」的不变式：当天还没出过结论时，error 照旧写主位、页面照常能看到它。"""
        archive.publish_day(_entry("error", "起跑即败"), None, root=self.root)
        self.assertEqual(self._read()["state"], "error")
        self.assertFalse((self._dir() / archive.ERROR_SIDECAR).exists())

    def test_conclusion_published_later_replaces_stale_error(self):
        """先挂后出结论：主位由结论接管（页面看的就是结论），此时不该有 sidecar 残影。"""
        archive.publish_day(_entry("error", "先挂一次"), None, root=self.root)
        archive.publish_day(_entry("red", "存在回归"), "# 回归报告", root=self.root)
        self.assertEqual(self._read()["state"], "red")
        self.assertIsNone(archive.read_day_error(self._dir()))

    def test_corrupt_conclusion_does_not_block_error(self):
        """主位文件读不出（损坏）按「没有结论」处理：error 照旧写主位，别让坏文件把失败也挤到边角。"""
        (self._dir()).mkdir(parents=True, exist_ok=True)
        (self._dir() / "nightly.json").write_text("{不是 json", encoding="utf-8")
        archive.publish_day(_entry("error", "补判未清零"), None, root=self.root)
        self.assertEqual(self._read()["state"], "error")

    def test_error_carrying_a_report_does_not_clobber_conclusion_report(self):
        """CLI 侧可能连报告一起交上来：结论已在时报告也不得覆盖，否则丢的就是那份能看的报告。"""
        archive.publish_day(_entry("green"), "# 真报告", root=self.root)
        archive.publish_day(_entry("error", "挂了"), "# 挂那次的报告", root=self.root)
        self.assertEqual((self._dir() / "report.md").read_text(encoding="utf-8"), "# 真报告")
        self.assertEqual(self._read(archive.ERROR_SIDECAR)["note"], "挂了")

    def test_read_day_error_roundtrip(self):
        self.assertIsNone(archive.read_day_error(self._dir()))
        archive.publish_day(_entry("green"), "# r", root=self.root)
        archive.publish_day(_entry("error", "判分缺失"), None, root=self.root)
        self.assertEqual(archive.read_day_error(self._dir())["note"], "判分缺失")
        (self._dir() / archive.ERROR_SIDECAR).write_text("[坏的文件]", encoding="utf-8")
        self.assertIsNone(archive.read_day_error(self._dir()))


if __name__ == "__main__":
    unittest.main()
