"""阶段 2a 测试：session pool key 带 scope_hash；make_policy_config_factory 消费 ScopeContext。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

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
