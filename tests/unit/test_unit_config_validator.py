"""config_validator：.env 文件缺失≠配置缺失（compose env_file 注入进程环境的容器部署不误报，
真·真空配置仍能报缺失；文件缺失时 *_CONFIGS 漂移照常逐项检出）。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
P = os.path.join(ROOT, "services", "shared", "src")
if P not in sys.path:
    sys.path.insert(0, P)

from shared.config_validator import validate_env  # noqa: E402

_ALL_KEYS = ("LLM_CONFIGS", "MINERU_CONFIGS", "POPO_CONFIGS", "EMBEDDING_CONFIGS", "RERANKER_CONFIGS")

_VALID = {
    "LLM_CONFIGS": json.dumps([{"name": "m", "base_url": "https://llm/api"}]),
    "MINERU_CONFIGS": json.dumps([{"name": "m", "url": "https://m/api", "api_key": "k"}]),
    "POPO_CONFIGS": json.dumps([{"name": "m", "url": "https://p/api", "api_key": "k", "model": "popo"}]),
    "EMBEDDING_CONFIGS": "",
    "RERANKER_CONFIGS": "",
}


class TestMissingEnvFile(unittest.TestCase):
    def setUp(self):
        # tmp 空目录作 cwd：_env_file_path 向上找不到任何 .env
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = mock.patch.object(Path, "cwd", return_value=Path(self._tmp.name))
        self._cwd.start()
        self.addCleanup(self._cwd.stop)
        self.addCleanup(self._tmp.cleanup)

    def _validate(self, **env):
        full = {k: "" for k in _ALL_KEYS}
        full.update(env)
        with mock.patch.dict(os.environ, full, clear=False):
            return validate_env()

    def test_env_injected_no_file_is_not_an_error(self):
        errors, warnings = self._validate(**_VALID)
        self.assertEqual(errors, [])
        # 可选缺省只出 warning，不再是文件缺失的 error
        self.assertTrue(any("EMBEDDING_CONFIGS" in w for w in warnings))

    def test_truly_empty_env_reports_missing(self):
        errors, _ = self._validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("[MISSING]", errors[0])
        self.assertIn("no *_CONFIGS", errors[0])

    def test_drift_still_detected_without_file(self):
        # 文件缺失不再早退：部分注入时必填项缺失照常逐项报漂移
        env = {k: v for k, v in _VALID.items() if k != "LLM_CONFIGS"}
        errors, _ = self._validate(**env)
        self.assertTrue(any("LLM_CONFIGS" in e and "[MISSING]" not in e for e in errors))


if __name__ == "__main__":
    unittest.main()
