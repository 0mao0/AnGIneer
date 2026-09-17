"""聊天历史路由测试（计划 §5 步 2）：列表/详情/删除/快照 PUT/claim/游客端点。

身份解析注入 resolve_principal，路由层不触碰真实鉴权中间件；
行级隔离、claim 先到先得、PUT 未知 msg_seq 拒（D10）、30 轮计数边界。
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/shared/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/chat-history/src")))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.history_store import scope_hash_for  # noqa: E402

from chat_history.routes import build_chat_router  # noqa: E402
from chat_history.store import SqliteHistoryStore  # noqa: E402


def _make_app(store, principal=("u:1", 1), guest_rounds=30):
    app = FastAPI()
    app.state.principal = principal

    def resolve_principal(request: Request):
        return request.app.state.principal

    app.include_router(build_chat_router(store, resolve_principal, guest_rounds=guest_rounds), prefix="/api/chat")
    return TestClient(app)


class ChatHistoryRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteHistoryStore(os.path.join(self.tmp.name, "chat.sqlite"))
        self.scope = scope_hash_for("default", [])
        self.client = _make_app(self.store)
        self.addCleanup(self.tmp.cleanup)

    def _chat(self, owner, sid, n=1):
        msgs = []
        for i in range(n):
            msgs += [
                AgentMessage(role="user", content=f"问题 {i}：什么是锚固长度？"),
                AgentMessage(role="assistant", content=f"回答 {i} [K1]", meta={"citations": [{"id": "K1"}]}),
            ]
        return self.store.append(owner, sid, self.scope, msgs, {"run_id": f"r-{sid}", "status": "completed"})

    # ------------------------------------------------ 列表/详情

    def test_list_sessions_sorted_and_titled(self):
        self._chat("u:1", "s1")
        self._chat("u:1", "s2")
        data = self.client.get("/api/chat/sessions").json()
        self.assertEqual(len(data["sessions"]), 2)
        titles = {s["id"]: s["title"] for s in data["sessions"]}
        self.assertTrue(titles["s1"].startswith("问题 0"))
        self.assertTrue(all(set(s) >= {"id", "scene", "libraryId", "title", "createdAt", "updatedAt"}
                            for s in data["sessions"]))

    def test_list_isolated_by_owner(self):
        self._chat("u:1", "s1")
        self._chat("u:2", "s9")
        self.client.app.state.principal = ("u:1", 1)
        ids = [s["id"] for s in self.client.get("/api/chat/sessions").json()["sessions"]]
        self.assertEqual(ids, ["s1"])

    def test_list_filter_by_library(self):
        self.store.append("u:1", "s1", scope_hash_for("lib-a", []),
                          [AgentMessage(role="user", content="hi lib-a")],
                          {"run_id": "r1", "status": "completed", "library_id": "lib-a"})
        self._chat("u:1", "s2")
        data = self.client.get("/api/chat/sessions", params={"library_id": "lib-a"}).json()
        self.assertEqual([s["id"] for s in data["sessions"]], ["s1"])

    def test_get_session_messages_shape(self):
        seqs = self._chat("u:1", "s1")
        data = self.client.get("/api/chat/sessions/s1").json()
        self.assertEqual(data["session"]["id"], "s1")
        self.assertEqual(len(data["messages"]), 2)
        m = data["messages"][1]
        self.assertEqual(m["msgSeq"], seqs[1])
        self.assertEqual(m["role"], "assistant")
        self.assertEqual(m["citations"], [{"id": "K1"}])  # meta 展平进消息（AIChatMessage 形状）

    def test_get_session_404_cross_owner(self):
        self._chat("u:2", "s9")
        self.assertEqual(self.client.get("/api/chat/sessions/s9").status_code, 404)

    # ------------------------------------------------ 快照 PUT（D10）

    def test_patch_meta_merges_display_fields(self):
        seqs = self._chat("u:1", "s1")
        resp = self.client.put("/api/chat/sessions/s1/messages", json={
            "patches": [{"msg_seq": seqs[1], "meta_patch": {"thinking_trace": [{"kind": "note", "detail": "x"}]}}],
        })
        self.assertEqual(resp.status_code, 200)
        m = self.client.get("/api/chat/sessions/s1").json()["messages"][1]
        self.assertEqual(m["thinking_trace"], [{"kind": "note", "detail": "x"}])
        self.assertEqual(m["citations"], [{"id": "K1"}])  # 原 meta 保留（浅合并）

    def test_patch_unknown_seq_rejected(self):
        self._chat("u:1", "s1")
        resp = self.client.put("/api/chat/sessions/s1/messages", json={
            "patches": [{"msg_seq": 999, "meta_patch": {"x": 1}}],
        })
        self.assertEqual(resp.status_code, 400)

    def test_patch_cross_owner_404(self):
        seqs = self._chat("u:2", "s9")
        resp = self.client.put("/api/chat/sessions/s9/messages", json={
            "patches": [{"msg_seq": seqs[0], "meta_patch": {"x": 1}}],
        })
        self.assertEqual(resp.status_code, 400)  # u:1 桶下无此 seq

    # ------------------------------------------------ 删除

    def test_delete_session(self):
        self._chat("u:1", "s1")
        self.assertEqual(self.client.delete("/api/chat/sessions/s1").status_code, 200)
        self.assertEqual(self.client.get("/api/chat/sessions/s1").status_code, 404)
        self.assertEqual(self.client.delete("/api/chat/sessions/s1").status_code, 404)

    def test_delete_by_library(self):
        self.store.append("u:1", "s1", scope_hash_for("lib-a", []),
                          [AgentMessage(role="user", content="hi")],
                          {"run_id": "r1", "status": "completed", "library_id": "lib-a"})
        self._chat("u:1", "s2")  # default 库
        resp = self.client.delete("/api/chat/sessions", params={"library_id": "lib-a"})
        self.assertEqual(resp.json()["deleted"], 1)
        self.assertEqual([s["id"] for s in self.client.get("/api/chat/sessions").json()["sessions"]], ["s2"])

    # ------------------------------------------------ claim

    def test_claim_moves_guest_sessions(self):
        self.store.touch_guest("g1")
        self._chat("g:g1", "s1")
        resp = self.client.post("/api/chat/sessions/claim", json={"guest_id": "g1"})
        self.assertEqual(resp.json()["claimed"], 1)
        ids = [s["id"] for s in self.client.get("/api/chat/sessions").json()["sessions"]]
        self.assertEqual(ids, ["s1"])  # 已并入 u:1 桶

    def test_claim_requires_login(self):
        self.client.app.state.principal = ("ip:abc", None)
        resp = self.client.post("/api/chat/sessions/claim", json={"guest_id": "g1"})
        self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------ 游客端点（步 3 前置：签发/幂等/计数）

    def test_guest_issue_idempotent_and_httponly(self):
        resp = self.client.post("/api/chat/guest")
        self.assertEqual(resp.status_code, 200)
        gid = resp.json()["guest_id"]
        self.assertIn("ag_guest_id", resp.cookies)
        # 带 cookie 再来：幂等返回同一 id，不重复 set
        resp2 = self.client.post("/api/chat/guest", cookies={"ag_guest_id": gid})
        self.assertEqual(resp2.json()["guest_id"], gid)

    def test_guest_round_count(self):
        self.store.touch_guest("g1")
        self.assertEqual(self.store.count_user_messages("g:g1"), 0)
        self._chat("g:g1", "s1", n=29)
        self.assertEqual(self.store.count_user_messages("g:g1"), 29)
        self._chat("g:g1", "s1", n=1)
        self.assertEqual(self.store.count_user_messages("g:g1"), 30)  # 第 30 轮仍放行边界

    def test_store_unavailable_503(self):
        client = _make_app(None)
        self.assertEqual(client.get("/api/chat/sessions").status_code, 503)


if __name__ == "__main__":
    unittest.main()
