"""angineer-core [server] 壳管道测试：health / 鉴权门 / SSE 帧管线 / 归一化镜像。

不触网、不调 LLM：分类以桩替身注入（返回 None → fallback 决策），会话以
FakeSession 替身（emit run_start/run_end 即收尾）。专测帧协议封装
（frame_version / route_debug 首帧 / [DONE]）与可选 Token 门。
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from angineer_core.agent_events import AgentEvent  # noqa: E402
from angineer_core.base_contracts import normalize_library_ids  # noqa: E402


class _FakeSession:
    def __init__(self):
        self.history = []
        self.cancelled = False

    def wait_for_idle(self, timeout=None):
        return True

    def run(self, user_text, emit=None, config_factory=None):
        emit(AgentEvent(type="run_start", run_id="stub-run", payload={}))
        emit(AgentEvent(type="run_end", run_id="stub-run", payload={"reason": "stub"}))
        return []

    def cancel(self):
        self.cancelled = True


def _client_and_module():
    import sys

    from angineer_core.server import app as shell_app

    return TestClient(shell_app), sys.modules["angineer_core.server.app"]


def test_health_ok():
    client, _ = _client_and_module()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "chat-api"
    assert body["status"] == "ok"


def test_normalize_library_ids_mirror_rules():
    assert normalize_library_ids(["a", "", "a", " b "], "") == ["a", "b"]
    assert normalize_library_ids(None, "x") == ["x"]
    assert normalize_library_ids([], "") == ["default"]
    assert normalize_library_ids(["a"], "fallback") == ["a"]


def test_sse_pipeline_frames():
    """请求 → SSE：stage / route_debug 首帧 / run 帧带 frame_version / [DONE]。"""
    client, mod = _client_and_module()
    fake = _FakeSession()

    async def _fake_classify(query, config_name=None, mode="instruct"):
        return None  # 分类降级 → fallback 决策（route_debug.fallback=true）

    env = {
        "ANGINEER_ROUTE_PARALLEL": "0",  # 关预检，测试不发后台线程
        "ANGINEER_DOCS_API_URL": "",     # 节点清单走降级路径（不触网）
    }
    with patch.dict(os.environ, env), \
         patch.object(mod, "get_agent_session", return_value=fake), \
         patch.object(mod, "_classify_offloaded", _fake_classify):
        resp = client.post(
            "/api/chat/agent",
            json={"query": "什么是设计低水位？", "library_id": "default"},
        )
    assert resp.status_code == 200
    assert resp.headers.get("x-chat-frame-version") == "1"
    body = resp.text
    assert '"stage": "classify"' in body
    assert '"type": "route_debug"' in body
    assert '"fallback": true' in body          # 分类失败 → fallback 决策透出
    assert '"type": "run_start"' in body
    assert '"type": "run_end"' in body
    assert '"frame_version": 1' in body
    assert body.rstrip().endswith("data: [DONE]")


def test_token_gate_optional():
    client, _ = _client_and_module()
    fake = _FakeSession()

    async def _fake_classify(query, config_name=None, mode="instruct"):
        return None

    _, mod = _client_and_module()
    env = {
        "ANGINEER_ROUTE_PARALLEL": "0",
        "ANGINEER_DOCS_API_URL": "",
        "ANGINEER_API_TOKEN": "s3cret-token",
    }
    with patch.dict(os.environ, env), \
         patch.object(mod, "get_agent_session", return_value=fake), \
         patch.object(mod, "_classify_offloaded", _fake_classify):
        # 无凭证 → 401；health 不受门保护
        assert client.post("/api/chat/agent", json={"query": "q"}).status_code == 401
        assert client.get("/health").status_code == 200
        # X-API-Key 正确 → 放行
        ok = client.post(
            "/api/chat/agent",
            json={"query": "q"},
            headers={"X-API-Key": "s3cret-token"},
        )
        assert ok.status_code == 200
        # Bearer 形态亦可
        ok2 = client.post(
            "/api/chat/agent",
            json={"query": "q"},
            headers={"Authorization": "Bearer s3cret-token"},
        )
        assert ok2.status_code == 200
