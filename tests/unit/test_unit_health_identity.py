"""回归测试：/health 响应携带 started_at/pid，供启动脚本识别端口被旧进程占用。"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))


class HealthIdentityTests(unittest.TestCase):
    def test_docs_api_health_carries_identity(self):
        import main as docs_main

        payload = docs_main.health()
        self.assertEqual(payload["status"], "ok")
        started = datetime.fromisoformat(payload["started_at"])
        self.assertLess((datetime.now() - started).total_seconds(), 3600)
        self.assertEqual(payload["pid"], os.getpid())


if __name__ == "__main__":
    unittest.main()
