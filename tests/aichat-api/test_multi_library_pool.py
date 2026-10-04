"""Phase D3 测试：会话池 key 去 scope_hash（阶段三 D6）。

池 key 新形态 ``owner:scene:session_id``：scope 每轮经 config_factory 新鲜注入，
换集合/换文档范围不换会话（同 session_id 跨集合续接）；owner 身份隔离位必须保留。
``_session_pool_key`` 的 library_id/doc_ids 参数保留仅为兼容旧调用签名。
"""
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

import chat_agent  # noqa: E402


def _clear_pool():
    chat_agent._AGENT_SESSION_POOL.clear()
    chat_agent._AGENT_SESSION_LAST_ACTIVE.clear()


class TestPoolKeySessionLevel(unittest.TestCase):
    def setUp(self):
        _clear_pool()
        self.addCleanup(_clear_pool)

    def test_scope_hash_not_in_key(self):
        key = chat_agent._session_pool_key("docs", "chat-1", "libA", [], owner="u:1")
        self.assertEqual(key, "u:1:docs:chat-1")

    def test_scope_change_does_not_change_key(self):
        """library_id/doc_ids 参数保留（旧调用签名兼容），但不再影响 key。"""
        k1 = chat_agent._session_pool_key("docs", "chat-1", "libA", ["d1"], owner="u:1")
        k2 = chat_agent._session_pool_key("docs", "chat-1", "libB", ["d2"], owner="u:1")
        self.assertEqual(k1, k2)

    def test_same_session_reused_across_scope_change(self):
        s1 = chat_agent.get_agent_session("docs", "chat-pool-test", library_id="libA",
                                          library_ids=["libA"], owner="u:t")
        s2 = chat_agent.get_agent_session("docs", "chat-pool-test", library_id="libB",
                                          library_ids=["libA", "libB"], owner="u:t")
        self.assertIs(s1, s2)  # 换集合不换会话（D5/D6）

    def test_history_continues_across_scope_change(self):
        """跨集合续接的可见症状：前一轮 history 在换集合后的同一会话里仍在。"""
        from angineer_core.agent_messages import AgentMessage

        s1 = chat_agent.get_agent_session("docs", "chat-pool-cont", library_id="libA",
                                          library_ids=["libA"], owner="u:t")
        s1.history.append(AgentMessage(role="user", content="第一问"))
        s2 = chat_agent.get_agent_session("docs", "chat-pool-cont", library_id="libB",
                                          library_ids=["libB", "libC"], owner="u:t")
        self.assertIs(s1, s2)
        self.assertEqual(len(s2.history), 1)

    def test_owner_isolation_survives_scope_removal(self):
        """D6 只去 scope，不碰身份隔离：同 session_id 不同 owner 必须仍分会话。"""
        a = chat_agent.get_agent_session("docs", "chat-pool-owner", library_id="libA",
                                         library_ids=["libA"], owner="u:1")
        b = chat_agent.get_agent_session("docs", "chat-pool-owner", library_id="libA",
                                         library_ids=["libA"], owner="u:2")
        self.assertIsNot(a, b)

    def test_legacy_call_signature_still_works(self):
        """旧调用（不传 library_ids）不因签名收紧而炸。"""
        s1 = chat_agent.get_agent_session("docs", "chat-pool-legacy", "libA", ["d1"], "u:t")
        self.assertIsInstance(s1, chat_agent.AgentSession)


if __name__ == "__main__":
    unittest.main()
