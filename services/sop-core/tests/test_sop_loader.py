"""SOP 加载稳定性的回归测试。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch


SOP_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SOP_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(SOP_CORE_SRC))

from sop_core.sop_loader import SopLoader


class SopLoaderStabilityTests(unittest.TestCase):
    """验证损坏 JSON SOP 会被跳过并留下可观测错误。"""

    def test_load_json_sop_returns_none_and_reason_for_invalid_steps(self) -> None:
        """非法步骤结构应返回 None，并记录到 load_errors。"""
        loader = SopLoader("D:/fake-sops")
        with patch("builtins.open", mock_open(read_data='{"id":"bad","steps":[{"tool":1}]}')):
            with patch("os.path.exists", return_value=True):
                sop = loader._load_json_sop("bad")

        self.assertIsNone(sop)
        self.assertIn("bad", loader.load_errors)


if __name__ == "__main__":
    unittest.main()
