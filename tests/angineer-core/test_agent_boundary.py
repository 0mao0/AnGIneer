"""P2 边界约束：agent_loop 不允许反向依赖 dispatcher/classifier/memory。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))


class AgentLoopBoundaryTests(unittest.TestCase):
    def test_agent_loop_has_no_reverse_imports(self):
        source = Path(__file__).resolve().parents[2] / "services/angineer-core/src/angineer_core/agent_loop.py"
        text = source.read_text(encoding="utf-8")
        for forbidden in ("dispatcher", "classifier", "memory"):
            self.assertNotIn(f"import {forbidden}", text)
            self.assertNotIn(f"from angineer_core.{forbidden}", text)


if __name__ == "__main__":
    unittest.main()
