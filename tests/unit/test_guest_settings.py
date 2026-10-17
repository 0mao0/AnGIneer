"""shared.guest_settings 单元测试（游客设置三键：默认/优先级/读坏 fail-closed/校验/原子写）。"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/shared/src")))

from shared import guest_settings  # noqa: E402


class GuestSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.path = os.path.join(self.tmp, "guest_settings.json")
        self._env = patch.dict(os.environ, {"GUEST_SETTINGS_FILE": self.path})
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("ANGINEER_GUEST_ROUNDS", None)

    def _write_raw(self, text):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _write(self, cfg):
        self._write_raw(json.dumps(cfg, ensure_ascii=False))

    # ---- 默认与优先级 ----

    def test_defaults_when_file_absent(self):
        cfg = guest_settings.load_guest_settings()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["rounds"], 30)
        self.assertEqual(cfg["library_ids"], ["default"])
        self.assertEqual(cfg["load_error"], "")

    def test_env_rounds_when_file_absent(self):
        with patch.dict(os.environ, {"ANGINEER_GUEST_ROUNDS": "5"}):
            self.assertEqual(guest_settings.effective_rounds(), 5)

    def test_file_overrides_env(self):
        self._write({"enabled": True, "rounds": 7, "library_ids": ["default"]})
        with patch.dict(os.environ, {"ANGINEER_GUEST_ROUNDS": "5"}):
            self.assertEqual(guest_settings.effective_rounds(), 7)

    # ---- 读坏 fail-closed（对齐 nightly「读坏禁跑」哲学） ----

    def test_corrupt_json_fail_closed(self):
        self._write_raw("{ 半截")
        cfg = guest_settings.load_guest_settings()
        self.assertFalse(cfg["enabled"])
        self.assertTrue(cfg["load_error"])

    def test_invalid_content_fail_closed(self):
        self._write({"enabled": True, "rounds": 0, "library_ids": []})
        cfg = guest_settings.load_guest_settings()
        self.assertFalse(cfg["enabled"])
        self.assertTrue(cfg["load_error"])
        self.assertEqual(cfg["library_ids"], ["default"])  # fail-closed 回默认集

    # ---- 规范化（保存路径） ----

    def test_normalize_rejects(self):
        for bad in (
            "not-dict",
            {"enabled": "yes", "rounds": 30, "library_ids": ["default"]},
            {"enabled": True, "rounds": 0, "library_ids": ["default"]},
            {"enabled": True, "rounds": 1001, "library_ids": ["default"]},
            {"enabled": True, "rounds": True, "library_ids": ["default"]},
            {"enabled": True, "rounds": 30, "library_ids": []},
            {"enabled": True, "rounds": 30, "library_ids": ["  "]},
        ):
            with self.assertRaises(ValueError):
                guest_settings.normalize_guest_settings(bad)

    # ---- 原子写 ----

    def test_save_roundtrip_and_atomic(self):
        saved = guest_settings.save_guest_settings(
            {"enabled": False, "rounds": 3, "library_ids": ["guifan", " default "]}
        )
        self.assertEqual(saved["library_ids"], ["guifan", "default"])  # 去空白
        cfg = guest_settings.load_guest_settings()
        self.assertEqual(
            cfg,
            {"enabled": False, "rounds": 3, "library_ids": ["guifan", "default"], "load_error": ""},
        )
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_save_creates_parent_dir(self):
        nested = os.path.join(self.tmp, "platform", "guest_settings.json")
        with patch.dict(os.environ, {"GUEST_SETTINGS_FILE": nested}):
            guest_settings.save_guest_settings({"enabled": True, "rounds": 30, "library_ids": ["default"]})
        self.assertTrue(os.path.exists(nested))

    # ---- 帮助函数 ----

    def test_helpers(self):
        self._write({"enabled": False, "rounds": 9, "library_ids": ["a", "b"]})
        self.assertFalse(guest_settings.guest_enabled())
        self.assertEqual(guest_settings.effective_rounds(), 9)
        self.assertEqual(guest_settings.guest_library_ids(), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
