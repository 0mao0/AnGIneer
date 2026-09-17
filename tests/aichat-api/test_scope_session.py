"""阶段 2a 测试：session pool key 带 scope_hash（+ 2026-09-17 起的 owner 隔离位）；
make_policy_config_factory 消费 ScopeContext。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.base_contracts import ScopeContext  # noqa: E402

import chat_agent  # noqa: E402


def _clear_pool():
    chat_agent._AGENT_SESSION_POOL.clear()
    chat_agent._AGENT_SESSION_LAST_ACTIVE.clear()


class SessionScopeKeyTests(unittest.TestCase):
    def setUp(self):
        _clear_pool()
        self.addCleanup(_clear_pool)

    def test_same_scope_reuses_session(self):
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[])
        s2 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[])
        self.assertIs(s1, s2)

    def test_different_library_opens_new_session(self):
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="lib-a", doc_ids=[])
        s2 = chat_agent.get_agent_session("qa", "s1", library_id="lib-b", doc_ids=[])
        self.assertIsNot(s1, s2)
        s3 = chat_agent.get_agent_session("qa", "s1", library_id="lib-a", doc_ids=[])
        self.assertIs(s1, s3)

    def test_different_doc_ids_opens_new_session(self):
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=["d1"])
        s2 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=["d2"])
        self.assertIsNot(s1, s2)

    def test_doc_ids_order_is_irrelevant(self):
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=["d1", "d2"])
        s2 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=["d2", "d1"])
        self.assertIs(s1, s2)

    def test_default_scope_key_stable(self):
        """default 单库行为不变：key 不因实现细节漂移。"""
        key1 = chat_agent._session_pool_key("qa", "s1", "default", [])
        key2 = chat_agent._session_pool_key("qa", "s1", "default", [])
        self.assertEqual(key1, key2)
        self.assertIn("qa", key1)
        self.assertIn("s1", key1)


class SessionOwnerIsolationTests(unittest.TestCase):
    """池 key 的身份隔离位：同 session_id、不同 owner 必须各开一个会话。

    2026-09-17：session_id 由客户端生成（``chat-<毫秒时间戳>``，可枚举），此前池 key 只有
    ``scene:session_id:scope_hash``，同库不同用户可以命中同一份 history——线上匿名可达时
    即等于「猜 id 读他人对话上下文」。owner 上 key 后这条路径被切断。
    """

    def setUp(self):
        _clear_pool()
        self.addCleanup(_clear_pool)

    def test_same_owner_reuses_session(self):
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="u:1")
        s2 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="u:1")
        self.assertIs(s1, s2)

    def test_different_owner_same_session_id_is_isolated(self):
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="u:1")
        s2 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="u:2")
        s3 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="ip:abc123")
        self.assertIsNot(s1, s2)
        self.assertIsNot(s1, s3)
        self.assertIsNot(s2, s3)

    def test_history_not_shared_across_owners(self):
        """真实症状回归：A 的 history 不得出现在 B 的会话里。"""
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="u:1")
        s1.history.append(AgentMessage(role="user", content="A 的私密问题"))
        s1.history.append(AgentMessage(role="assistant", content="A 的私密回答"))

        s2 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="u:2")
        self.assertEqual(s2.history, [])

    def test_api_key_and_user_buckets_are_distinct(self):
        """API key（k:）与会话用户（u:）即使数字 id 相同也不得共池。"""
        s1 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="u:7")
        s2 = chat_agent.get_agent_session("qa", "s1", library_id="default", doc_ids=[], owner="k:7")
        self.assertIsNot(s1, s2)


class FactoryScopeTests(unittest.TestCase):
    def test_factory_consumes_scope_context(self):
        captured = {}

        def fake_build_attempts(**kwargs):
            captured.update(kwargs)
            return []

        scope = ScopeContext(library_id="lib-x", doc_ids=["d9"])
        factory = chat_agent.make_policy_config_factory(
            "docs",
            scope=scope,
            intent_result=None,
            sop_loader=None,
        )
        with patch("angineer_core.agent_policy.build_attempts", side_effect=fake_build_attempts):
            factory()

        self.assertEqual(captured["library_id"], "lib-x")
        self.assertEqual(captured["doc_ids"], ["d9"])


if __name__ == "__main__":
    unittest.main()
