"""阶段 1b 测试：Router 前置 route_request -> RouteDecision，SSE 首帧 route_debug，flag 可回退。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_events import AgentEvent  # noqa: E402
from angineer_core.base_contracts import IntentResult  # noqa: E402

import importlib  # noqa: E402

import route_pre  # noqa: E402

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))


def _load_main():
    """按归属加载 aichat-api 的 main：sys.path 可能被其他服务测试顶占，需校验 __file__。"""
    if _AICHAT_DIR not in sys.path:
        sys.path.insert(0, _AICHAT_DIR)
    loaded = sys.modules.get("main")
    if loaded is not None:
        owner = os.path.abspath(getattr(loaded, "__file__", "") or "")
        if not owner.lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop("main", None)
            loaded = None
    if loaded is None:
        sys.path.insert(0, _AICHAT_DIR)
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


def _intent(level="L2", service_mode="sql_first", reason="规则命中"):
    return IntentResult(
        intent_level=level,
        primary_level=level,
        service_mode=service_mode,
        execution_plan=[service_mode],
        reason=reason,
    )


class RouteRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_decision_carries_debug_and_scope(self):
        async def fake_classify(query, config_name, mode):
            return _intent()

        decision = await route_pre.route_request(
            query="q", scene="docs", library_id="lib-a", doc_ids=["d1"],
            config_name=None, mode="instruct", classify=fake_classify,
        )
        self.assertFalse(decision.fallback)
        self.assertEqual(decision.route_debug.level, "L2")
        self.assertEqual(decision.route_debug.service_mode, "sql_first")
        self.assertEqual(decision.route_debug.reason, "规则命中")
        self.assertFalse(decision.route_debug.fallback)
        self.assertEqual(decision.scope.library_id, "lib-a")
        self.assertEqual(decision.scope.doc_ids, ["d1"])
        self.assertEqual(decision.attempts, ["sql_first"])
        self.assertIs(decision.intent_result.intent_level, "L2")

    async def test_classify_none_yields_fallback_decision_with_scope(self):
        async def none_classify(query, config_name, mode):
            return None

        decision = await route_pre.route_request(
            query="q", scene="docs", library_id="lib-b", doc_ids=[],
            config_name=None, mode="instruct", classify=none_classify,
        )
        self.assertTrue(decision.fallback)
        self.assertTrue(decision.route_debug.fallback)
        self.assertTrue(decision.route_debug.reason)
        self.assertEqual(decision.scope.library_id, "lib-b")
        self.assertIsNone(route_pre.decision_intent_result(decision))

    async def test_decision_intent_result_passthrough_on_success(self):
        async def fake_classify(query, config_name, mode):
            return _intent(level="L1", service_mode="semantic_retrieval")

        decision = await route_pre.route_request(
            query="q", scene="qa", library_id=None, doc_ids=None,
            config_name=None, mode="instruct", classify=fake_classify,
        )
        self.assertEqual(decision.scope.library_id, "default")
        self.assertIs(route_pre.decision_intent_result(decision), decision.intent_result)


class RoutePreFlagTests(unittest.TestCase):
    def test_default_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(route_pre.ROUTE_PRE_ENV, None)
            self.assertTrue(route_pre.route_pre_enabled())

    def test_disabled_values(self):
        for value in ("false", "0", "no", "off"):
            with patch.dict(os.environ, {route_pre.ROUTE_PRE_ENV: value}):
                self.assertFalse(route_pre.route_pre_enabled(), value)


class _FakeSession:
    def __init__(self):
        self.cancelled = False

    def run(self, query, emit, config_factory):
        emit(AgentEvent(type="run_start", run_id="r1"))
        emit(AgentEvent(type="run_end", run_id="r1", payload={"reason": "completed"}))

    def cancel(self):
        self.cancelled = True


def _read_frames(response):
    frames = []
    for line in response.iter_lines():
        if line.startswith("data: ") and line != "data: [DONE]":
            import json

            frames.append(json.loads(line[len("data: "):]))
    return frames


class RoutePreSseTests(unittest.TestCase):
    def _post_chat(self, frames_sink, **patch_kwargs):
        from fastapi.testclient import TestClient

        main = _load_main()
        self.addCleanup(_unload_aichat_modules)
        fake_session = _FakeSession()
        with patch.object(main, "get_agent_session", return_value=fake_session), \
             patch.object(main, "classify_intent_offloaded", new=patch_kwargs["classify"]), \
             patch.object(main, "route_pre_enabled", return_value=patch_kwargs["enabled"]):
            client = TestClient(main.app)
            with client.stream(
                "POST", "/api/chat/agent",
                json={"query": "q", "scene": "docs", "library_id": "lib-a", "doc_ids": ["d1"]},
            ) as response:
                frames_sink.extend(_read_frames(response))
        return fake_session

    def test_first_frame_is_route_debug_on_success(self):
        async def fake_classify(query, config_name, mode):
            return _intent()

        frames = []
        self._post_chat(frames, classify=fake_classify, enabled=True)
        self.assertGreaterEqual(len(frames), 3)
        self.assertEqual(frames[0]["type"], "route_debug")
        debug = frames[0]["payload"]["route_debug"]
        self.assertEqual(debug["level"], "L2")
        self.assertEqual(debug["service_mode"], "sql_first")
        self.assertEqual(debug["reason"], "规则命中")
        self.assertFalse(debug["fallback"])
        self.assertEqual(frames[0]["payload"]["scope"]["library_id"], "lib-a")
        self.assertEqual(frames[1]["type"], "run_start")
        self.assertEqual(frames[-1]["type"], "run_end")

    def test_fallback_frames_when_classifier_fails(self):
        async def none_classify(query, config_name, mode):
            return None

        frames = []
        self._post_chat(frames, classify=none_classify, enabled=True)
        self.assertEqual(frames[0]["type"], "route_debug")
        self.assertTrue(frames[0]["payload"]["route_debug"]["fallback"])
        self.assertEqual(frames[0]["payload"]["scope"]["library_id"], "lib-a")
        self.assertEqual(frames[1]["type"], "note")
        self.assertIn("路由失败", frames[1]["payload"]["detail"])

    def test_flag_off_keeps_legacy_first_frame(self):
        async def fake_classify(query, config_name, mode):
            return _intent()

        frames = []
        self._post_chat(frames, classify=fake_classify, enabled=False)
        self.assertEqual(frames[0]["type"], "run_start")
        self.assertNotIn("route_debug", [f["type"] for f in frames])


if __name__ == "__main__":
    unittest.main()
