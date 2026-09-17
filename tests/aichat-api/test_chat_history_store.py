"""聊天历史存储测试（计划 §5 步 1/§6）。

覆盖：HistoryStore 协议两方法、round-trip（含 tool_calls/meta）、seq 服务端权威、
行级隔离（跨 owner 查不到）、scope_hash 过滤、回灌仅池内新建触发一次（D11）、
claim 改挂与在跑 run 跟随（§8，步 2 语义先行验证 DAO 层）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/shared/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/chat-history/src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))

from angineer_core.agent_messages import AgentMessage, ToolCall  # noqa: E402
from angineer_core.history_store import scope_hash_for  # noqa: E402

from chat_history.store import SqliteHistoryStore  # noqa: E402

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))


def _import_chat_agent():
    """强制目录置顶 + 清同名幽灵模块（与 test_chat_auth_scope 的 _load_aichat_module 同因）。"""
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)
    sys.path.insert(0, _AICHAT_DIR)
    loaded = sys.modules.get("chat_agent")
    if loaded is not None:
        owner = os.path.abspath(getattr(loaded, "__file__", "") or "")
        if not owner.lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop("chat_agent", None)
    return __import__("chat_agent")


def _msgs():
    return [
        AgentMessage(role="user", content="什么是锚固长度？"),
        AgentMessage(role="assistant", content="锚固长度是……[K1]", meta={"citations": [{"id": "K1"}]}),
    ]


class StoreProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "chat.sqlite")
        self.store = SqliteHistoryStore(self.db)
        self.scope = scope_hash_for("default", [])
        self.addCleanup(self.tmp.cleanup)

    def test_append_load_roundtrip(self):
        seqs = self.store.append("u:1", "s1", self.scope, _msgs(), {"run_id": "r1", "status": "completed"})
        self.assertEqual(seqs, [1, 2])
        loaded = self.store.load("u:1", "s1", self.scope)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].role, "user")
        self.assertEqual(loaded[1].content, "锚固长度是……[K1]")
        self.assertEqual(loaded[1].meta["citations"], [{"id": "K1"}])

    def test_append_tool_message_roundtrip(self):
        msgs = [
            AgentMessage(role="assistant", content="", tool_calls=[
                ToolCall(id="call_1_0", name="search", arguments={"q": "x"}),
            ]),
            AgentMessage(role="tool", content="工具结果", tool_call_id="call_1_0",
                         name="search", is_error=False),
        ]
        self.store.append("u:1", "s1", self.scope, msgs, {"run_id": "r2", "status": "completed"})
        loaded = self.store.load("u:1", "s1", self.scope)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].tool_calls[0].id, "call_1_0")
        self.assertEqual(loaded[1].tool_call_id, "call_1_0")
        self.assertEqual(loaded[1].name, "search")

    def test_seq_is_server_authority_and_monotonic(self):
        s1 = self.store.append("u:1", "s1", self.scope, _msgs(), {"run_id": "a", "status": "completed"})
        s2 = self.store.append("u:1", "s1", self.scope, _msgs(), {"run_id": "b", "status": "completed"})
        self.assertEqual(s1, [1, 2])
        self.assertEqual(s2, [3, 4])

    def test_row_level_isolation_between_owners(self):
        self.store.append("u:1", "s1", self.scope, _msgs(), {"run_id": "a", "status": "completed"})
        self.assertEqual(self.store.load("u:2", "s1", self.scope), [])
        self.assertEqual(self.store.load("u:1", "s2", self.scope), [])

    def test_scope_hash_filtering(self):
        other_scope = scope_hash_for("lib-a", [])
        self.store.append("u:1", "s1", self.scope, _msgs(), {"run_id": "a", "status": "completed"})
        self.store.append("u:1", "s1", other_scope, _msgs(), {"run_id": "b", "status": "completed"})
        self.assertEqual(len(self.store.load("u:1", "s1", self.scope)), 2)
        self.assertEqual(len(self.store.load("u:1", "s1", other_scope)), 2)
        # 换库/文档集 → 新 scope，互不串
        self.assertEqual(self.store.load("u:1", "s1", scope_hash_for("default", ["d1"])), [])

    def test_empty_messages_noop(self):
        self.assertEqual(self.store.append("u:1", "s1", self.scope, [], {"run_id": "a"}), [])


class HydrationOnceTests(unittest.TestCase):
    """D11：回灌只在池内新建 session 时触发一次；池命中不灌（内存 history 已是真相）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteHistoryStore(os.path.join(self.tmp.name, "chat.sqlite"))
        self.scope = scope_hash_for("default", [])
        self.store.append("u:1", "s1", self.scope, _msgs(), {"run_id": "a", "status": "completed"})
        self.addCleanup(self.tmp.cleanup)

        self.chat_agent = _import_chat_agent()
        self.chat_agent._AGENT_SESSION_POOL.clear()
        self.chat_agent._AGENT_SESSION_LAST_ACTIVE.clear()
        self.addCleanup(self.chat_agent._AGENT_SESSION_POOL.clear)
        self.addCleanup(self.chat_agent._AGENT_SESSION_LAST_ACTIVE.clear)

    def test_loader_called_once_for_new_pool_session(self):
        calls = []

        def loader():
            calls.append(1)
            return self.store.load("u:1", "s1", self.scope)

        s1 = self.chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[],
                                               owner="u:1", history_loader=loader)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(s1.history), 2)  # 历史已灌入内存
        # 池命中：不再回灌
        s2 = self.chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[],
                                               owner="u:1", history_loader=loader)
        self.assertIs(s1, s2)
        self.assertEqual(len(calls), 1)

    def test_loader_failure_degrades_to_empty(self):
        def bad_loader():
            raise RuntimeError("db down")

        s = self.chat_agent.get_agent_session("qa", "s9", library_id="default", doc_ids=[],
                                              owner="u:1", history_loader=bad_loader)
        self.assertEqual(s.history, [])


class ClaimDaoTests(unittest.TestCase):
    """claim 改挂 + §8：append 落库 owner 以会话行当前归属为准（在跑 run 跟随新 owner）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteHistoryStore(os.path.join(self.tmp.name, "chat.sqlite"))
        self.scope = scope_hash_for("default", [])
        self.addCleanup(self.tmp.cleanup)

    def test_claim_moves_sessions_messages_and_runs(self):
        self.store.touch_guest("g1")
        self.store.append("g:g1", "s1", self.scope, _msgs(), {"run_id": "a", "status": "completed"})
        n = self.store.claim_guest("g:g1", "u:7", 7)
        self.assertEqual(n, 1)
        self.assertEqual(self.store.load("g:g1", "s1", self.scope), [])
        self.assertEqual(len(self.store.load("u:7", "s1", self.scope)), 2)
        # 重复 claim 幂等：先到先得
        self.assertEqual(self.store.claim_guest("g:g1", "u:8", 8), 0)
        self.assertEqual(len(self.store.load("u:8", "s1", self.scope)), 0)

    def test_append_follows_claimed_owner(self):
        self.store.touch_guest("g1")
        self.store.append("g:g1", "s1", self.scope, _msgs(), {"run_id": "a", "status": "completed"})
        self.store.claim_guest("g:g1", "u:7", 7)
        # 在跑 run 仍持旧 owner 写入：应落到新 owner 桶（会话行当前归属）
        seqs = self.store.append("g:g1", "s1", self.scope, _msgs(), {"run_id": "b", "status": "completed"})
        self.assertEqual(seqs, [3, 4])
        self.assertEqual(len(self.store.load("u:7", "s1", self.scope)), 4)
        self.assertEqual(self.store.load("g:g1", "s1", self.scope), [])


class GcTests(unittest.TestCase):
    """步 4：保留期 GC——过期行被清，活跃行保留，用户删除立即生效（delete 语义在步 2 路由测）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteHistoryStore(os.path.join(self.tmp.name, "chat.sqlite"))
        self.scope = scope_hash_for("default", [])
        self.addCleanup(self.tmp.cleanup)

    def test_gc_removes_expired_rows_only(self):
        self.store.append("u:1", "old", self.scope, _msgs(), {"run_id": "a", "status": "completed"})
        self.store.append("u:1", "fresh", self.scope, _msgs(), {"run_id": "b", "status": "completed"})
        self.store.touch_guest("old-guest")
        self.store.touch_guest("fresh-guest")
        # 把 old 会话/消息/run/游客整体回拨 100 天
        import sqlite3
        conn = sqlite3.connect(self.store._db_path)
        conn.execute(
            "UPDATE chat_messages SET created_at=? WHERE session_id='old'",
            (self._iso_days_ago(100),),
        )
        conn.execute(
            "UPDATE chat_sessions SET created_at=?, updated_at=? WHERE session_id='old'",
            (self._iso_days_ago(100), self._iso_days_ago(100)),
        )
        conn.execute(
            "UPDATE chat_runs SET created_at=? WHERE session_id='old'",
            (self._iso_days_ago(100),),
        )
        conn.execute(
            "UPDATE chat_guests SET last_seen_at=? WHERE guest_id='old-guest'",
            (self._iso_days_ago(100),),
        )
        conn.commit()
        conn.close()

        result = self.store.gc_expired(90)
        self.assertEqual(result["messages"], 2)
        self.assertEqual(result["sessions"], 1)
        self.assertEqual(result["runs"], 1)
        self.assertEqual(result["guests"], 1)
        # 新鲜行全保留
        self.assertEqual(len(self.store.load("u:1", "fresh", self.scope)), 2)
        self.assertIsNotNone(self.store.get_session("u:1", "fresh"))

    @staticmethod
    def _iso_days_ago(days):
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


if __name__ == "__main__":
    unittest.main()
