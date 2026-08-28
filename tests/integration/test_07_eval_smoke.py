"""冒烟门禁集成测试：服务可用且显式开启时跑 smoke 题集回归。

默认 skip（避免拖慢 harness）。启用方式：
    set ANGINEER_EVAL_SMOKE=1 && pnpm harness
或直接：
    pnpm harness:eval-smoke
"""
import os
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _aichat_api_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:8791/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


@unittest.skipUnless(os.getenv("ANGINEER_EVAL_SMOKE") == "1", "设置 ANGINEER_EVAL_SMOKE=1 启用冒烟门禁")
class EvalSmokeGateTests(unittest.TestCase):
    def test_smoke_gate_no_regression(self):
        if not _aichat_api_up():
            self.skipTest("aichat-api 未运行")
        proc = subprocess.run(
            [sys.executable, "scripts/open_ragbench/run_smoke.py"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=3600,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        self.assertEqual(proc.returncode, 0, f"冒烟门禁未通过:\n{output[-2000:]}")


if __name__ == "__main__":
    unittest.main()
