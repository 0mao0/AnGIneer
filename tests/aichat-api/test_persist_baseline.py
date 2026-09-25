"""落库基线竞态回归：hist_base 必须在 run_future 创建之前捕获。

2026-09-25 本地实踩：executor 线程 append 本轮 user 消息若先于主线程读 len(history)，
基线会把 user 消息误算进「历史」，run_end 切片把它丢掉——同一会话第 4 问落库缺 user 行
（前三问赢了竞态）。修复后捕获先于 executor 启动，切片必然包含 user。
"""
import json
import os
import sys
import unittest
import asyncio
from unittest.mock import patch

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))
sys.path.append(_AICHAT_DIR)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_events import AgentEvent  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402

import importlib  # noqa: E402


def _load_main():
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
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if path and os.path.abspath(path).lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop(name, None)
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)


class _RaceSession:
    """run() 一被调用就同步 append 本轮 user 消息——模拟 executor 线程赢下
    「append 先于主线程读基线」的竞态；基线若在 run_future 之后捕获必丢 user 行。"""

    def __init__(self, answer="答案"):
        self.history = []
        self._answer = answer

    def wait_for_idle(self, timeout=None):
        return True

    def run(self, query, emit, config_factory):
        self.history.append(AgentMessage(role="user", content=query))
        self.history.append(AgentMessage(role="assistant", content=self._answer))
        emit(AgentEvent(type="run_start", run_id="r1"))
        emit(AgentEvent(
            type="run_end", run_id="r1",
            payload={"reason": "completed", "messages": [], "notes": []},
        ))

    def cancel(self):
        pass


class _RecordingStore:
    def __init__(self):
        self.batches = []

    def append(self, owner, session_id, scope_hash, messages, run_meta):
        self.batches.append([(m.role, m.content) for m in messages])
        return list(range(1, len(messages) + 1))


def _inline_run_in_executor(self, executor, fn, *args):
    """同步执行 worker 函数：制造确定性竞态——run() 的 append 一定落在
    「pre-fix 代码读基线」之前。用真实线程池则取决于调度，复现不稳定。"""
    fut = asyncio.Future()
    try:
        fut.set_result(fn(*args))
    except Exception as exc:  # noqa: BLE001
        fut.set_exception(exc)
    return fut


class PersistBaselineRaceTests(unittest.TestCase):
    def test_persisted_batch_includes_user_message(self):
        from fastapi.testclient import TestClient

        main = _load_main()
        self.addCleanup(_unload_aichat_modules)
        session = _RaceSession()
        store = _RecordingStore()

        async def fake_classify(query, config_name, mode):
            return None

        with patch.object(main, "get_agent_session", return_value=session), \
             patch.object(main, "_get_history_store", return_value=store), \
             patch.object(main, "guest_gate_blocked", return_value=False), \
             patch.object(main, "route_pre_enabled", return_value=False), \
             patch.object(main, "classify_intent_offloaded", new=fake_classify), \
             patch.object(asyncio.BaseEventLoop, "run_in_executor", _inline_run_in_executor):
            client = TestClient(main.app)
            response = client.post(
                "/api/chat/agent",
                json={"query": "竞态探针问题", "scene": "qa", "session_id": "race-s1"},
            )

        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(len(store.batches), 1, "run_end 应触发一次落库")
        roles = [role for role, _ in store.batches[0]]
        self.assertEqual(roles[0], "user", "落库切片首条必须是本轮 user 消息（基线先于 executor 捕获）")
        self.assertEqual(store.batches[0][0][1], "竞态探针问题")
        self.assertEqual(roles, ["user", "assistant"])

        frames = [
            json.loads(line[len("data: "):])
            for line in response.iter_lines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        run_end = next(f for f in frames if f.get("type") == "run_end")
        self.assertEqual(run_end.get("msg_seqs"), [1, 2])


if __name__ == "__main__":
    unittest.main()
