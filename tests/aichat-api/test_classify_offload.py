"""阶段 1a 测试：意图分类卸载到 executor，不阻塞 SSE 事件循环；异常静默降级保持。"""
import asyncio
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))

import importlib  # noqa: E402

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))


def _load_main():
    """按归属加载 aichat-api 的 main：强制目录置顶 + 校验 __file__（同名包冲突防御）。"""
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)
    sys.path.insert(0, _AICHAT_DIR)
    loaded = sys.modules.get("main")
    if loaded is not None:
        owner = os.path.abspath(getattr(loaded, "__file__", "") or "")
        if not owner.lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop("main", None)
            loaded = None
    if loaded is None:
        loaded = importlib.import_module("main")
    return loaded


def _unload_aichat_modules():
    """清理 aichat-api 顶层包占用，恢复其他服务测试的 import 解析现场。"""
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if path and os.path.abspath(path).lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop(name, None)
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)


class ClassifyOffloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.main = _load_main()
        self.addCleanup(_unload_aichat_modules)

    async def test_classify_runs_on_worker_thread(self):
        seen = {}

        def fake_blocking(query, config_name, mode):
            seen["thread"] = threading.get_ident()
            return "intent"

        with patch.object(self.main, "_classify_intent_blocking", side_effect=fake_blocking):
            result = await self.main.classify_intent_offloaded("q", None, "instruct")

        self.assertEqual(result, "intent")
        self.assertIn("thread", seen)
        self.assertNotEqual(seen["thread"], threading.get_ident())

    async def test_event_loop_not_blocked_during_classify(self):
        def slow_blocking(query, config_name, mode):
            time.sleep(0.3)
            return "intent"

        ticks = 0
        stopped = False

        async def ticker():
            nonlocal ticks, stopped
            while not stopped:
                ticks += 1
                await asyncio.sleep(0.01)

        with patch.object(self.main, "_classify_intent_blocking", side_effect=slow_blocking):
            task = asyncio.create_task(ticker())
            result = await self.main.classify_intent_offloaded("q", None, "instruct")
            stopped = True
            await task

        self.assertEqual(result, "intent")
        self.assertGreater(ticks, 1, "事件循环在分类期间应能调度其他协程")

    async def test_classify_error_falls_back_to_none(self):
        def boom(query, config_name, mode):
            raise RuntimeError("llm down")

        with patch.object(self.main, "_classify_intent_blocking", side_effect=boom):
            result = await self.main.classify_intent_offloaded("q", None, "instruct")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
