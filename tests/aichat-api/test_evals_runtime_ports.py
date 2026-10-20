"""eval worker 拆分回归：worker 必须注册 docs-core 引擎端口。

2026-10-20 拆进程后 worker 只注入 probe/intent，漏了 register_engine_ports，
knowledge_search 报「本地知识检索不可用（端口未注册）」，正面题 0/60。
"""
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for rel in ("services/aichat-api", "services/angineer-core/src", "services/docs-core/src"):
    path = os.path.join(_ROOT, rel)
    if path not in sys.path:
        sys.path.insert(0, path)

from evals_runtime import register_engine_ports  # noqa: E402


class EvalWorkerPortsTests(unittest.TestCase):
    def test_register_engine_ports_wires_knowledge_search(self):
        from angineer_core import ports

        try:
            register_engine_ports()
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"docs-core 不可用: {exc}")

        self.assertIsNotNone(ports.get_knowledge_local_search())
        self.assertIsNotNone(ports.get_local_nodes_loader())


if __name__ == "__main__":
    unittest.main()
